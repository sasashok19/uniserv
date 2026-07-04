"""Integration test for the event bus (Feature 01).

Requires a live Valkey (the compose stack, exposed on localhost:6379). Skipped
automatically when no broker is reachable, so the unit suite stays hermetic.

Covers the 01_EVENT_BUS integration requirement:
  Publish event -> consumer receives within 500ms -> ACK confirmed.
"""

import asyncio
import time
from uuid import uuid4

import pytest
from valkey.asyncio import Valkey

from app.config import settings
from app.events import streams
from app.events.consumer import BaseConsumer
from app.events.event import build_event
from app.events.publisher import BasePublisher
from app.events.streams import stream_key

URL = settings.valkey_url


def _reachable() -> bool:
    async def _ping() -> bool:
        client = Valkey.from_url(URL, decode_responses=True)
        try:
            return bool(await client.ping())
        except Exception:
            return False
        finally:
            await client.aclose()

    try:
        return asyncio.run(_ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(), reason=f"no Valkey reachable at {URL}"
)


def test_publish_consume_ack_roundtrip_under_500ms():
    async def _roundtrip():
        client = Valkey.from_url(URL, decode_responses=True)
        tenant = f"itest-{uuid4().hex[:8]}"
        stream = streams.CHANNEL_MESSAGE_RECEIVED
        group = "uniserve-itest"
        key = stream_key(tenant, stream)

        publisher = BasePublisher(client, tenant)
        consumer = BaseConsumer(client, tenant, group=group, retry_delay_ms=0)

        # Create the group before publishing so the new message is delivered to it.
        await consumer._ensure_group(key)

        received = []

        async def handler(data):
            received.append(data)

        event = build_event(tenant, stream, {"text": "hello"})

        start = time.perf_counter()
        await publisher.publish(stream, event)
        processed = await consumer.consume(stream, group, handler, batch_size=10)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # ACK confirmed: no pending entries remain for the group.
        pending = await client.xpending(key, group)
        pending_count = pending["pending"] if isinstance(pending, dict) else pending[0]

        await client.delete(key)
        await client.aclose()

        return processed, received, elapsed_ms, pending_count

    processed, received, elapsed_ms, pending_count = asyncio.run(_roundtrip())

    assert processed == 1
    assert len(received) == 1
    assert received[0]["payload"] == {"text": "hello"}
    assert elapsed_ms < 500, f"round-trip took {elapsed_ms:.0f}ms"
    assert pending_count == 0
