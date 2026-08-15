"""Shared test fixtures.

Two rules this file exists to enforce.

**A unit test never makes a live OpenAI call.** `app.config.settings` loads
`.env.local`, which on a developer's machine holds a real `OPENAI_API_KEY` — so
any code path that gates an LLM call on "is a key configured?" (there are
several: ``app/classify/message_quality.py``, ``app/priority/llm_scorer.py``,
``app/tickets/chief_complaint.py``) would quietly reach the network from
`pytest`, making the suite slow, chargeable, and non-deterministic. Tests that
want the LLM path patch `settings` in their own module namespace as before,
which still wins over this.

**A unit test never reaches a live Valkey.** Added with Feature 26, which put
real conversation state behind Valkey (the WhatsApp menu session and the pending
duplicate-confirmation state). Every one of those reads is best-effort and
degrades to "no state", so without this the suite still passed — but it passed
by way of a connection attempt and a logged failure on every routing test, which
is both slow and a good way to never notice that a state read was meant to
succeed. The fake makes state a thing a test can set up and assert on.

Note ``test_event_bus_integration.py`` is unaffected: it builds its own
``Valkey.from_url`` directly and skips when no broker is reachable.
"""

import fnmatch
from unittest.mock import patch

import pytest

from app.config import settings
from app.events.client import get_valkey


class FakeValkey:
    """An in-memory stand-in for the async Valkey client.

    Covers only what ai-core actually calls: the string commands used for
    conversation/menu/PII state, and ``xadd`` for event publishing. TTLs are
    recorded rather than enforced — no test turns the clock forward, and a fake
    that silently expired keys would be harder to reason about than one that
    doesn't.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.streams: dict[str, list] = {}
        self._counter = 0

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, **_kwargs):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            removed += 1 if self.store.pop(key, None) is not None else 0
            self.ttls.pop(key, None)
        return removed

    async def exists(self, *keys):
        return sum(1 for key in keys if key in self.store)

    async def keys(self, pattern="*"):
        return [k for k in self.store if fnmatch.fnmatch(k, pattern)]

    async def ping(self):
        return True

    async def xadd(self, key, fields, **_kwargs):
        self._counter += 1
        message_id = f"{self._counter}-0"
        self.streams.setdefault(key, []).append((message_id, dict(fields)))
        return message_id

    async def aclose(self):
        return None


@pytest.fixture(autouse=True)
def no_live_llm_calls():
    original = settings.openai_api_key
    settings.openai_api_key = ""
    yield
    settings.openai_api_key = original


@pytest.fixture(autouse=True)
def fake_valkey():
    """Swap the shared Valkey client for an in-memory fake.

    Patches the constructor rather than ``get_valkey`` itself, because every
    consumer does ``from app.events.client import get_valkey`` and holds its own
    reference to the function — patching the name in one module would miss the
    rest. The ``lru_cache`` is cleared on both sides so neither the real client
    nor the fake leaks across the boundary.
    """
    fake = FakeValkey()
    with patch("app.events.client.Valkey") as valkey_cls:
        valkey_cls.from_url.return_value = fake
        get_valkey.cache_clear()
        try:
            yield fake
        finally:
            get_valkey.cache_clear()
