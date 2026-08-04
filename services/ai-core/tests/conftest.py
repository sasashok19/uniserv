"""Shared test fixtures.

The one rule this file exists to enforce: **a unit test never makes a live
OpenAI call.** `app.config.settings` loads `.env.local`, which on a
developer's machine holds a real `OPENAI_API_KEY` — so any code path that
gates an LLM call on "is a key configured?" (there are several:
``app/classify/message_quality.py``, ``app/priority/llm_scorer.py``,
``app/tickets/chief_complaint.py``) would quietly reach the network from
`pytest`, making the suite slow, chargeable, and non-deterministic. Tests
that want the LLM path patch `settings` in their own module namespace as
before, which still wins over this.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def no_live_llm_calls():
    original = settings.openai_api_key
    settings.openai_api_key = ""
    yield
    settings.openai_api_key = original
