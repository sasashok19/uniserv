"""Unit tests for the ai-core event bus (Feature 01).

These use a mocked Valkey client (no live broker), covering the unit-test
requirements in 01_EVENT_BUS:
  - Publisher writes to the correct stream with the correct shape
  - Consumer ACKs a message after a successful handler
  - Consumer sends to the DLQ after 3 retries
"""

import asyncio
import json
from unittest.mock import AsyncMock

from app.events import streams
from app.events.consumer import BaseConsumer
from app.events.event import build_event
from app.events.publisher import BasePublisher


def _run(coro):
    return asyncio.run(coro)


def test_publisher_writes_to_tenant_scoped_stream_with_shape():
    client = AsyncMock()
    client.xadd.return_value = "1-0"
    publisher = BasePublisher(client, tenant_id="acme")

    event = build_event("acme", streams.IDENTITY_RESOLVED, {"customerId": "C-1"}, trace_id="t-1")
    message_id = _run(publisher.publish(streams.IDENTITY_RESOLVED, event))

    assert message_id == "1-0"
    client.xadd.assert_awaited_once()
    key, fields = client.xadd.await_args.args
    assert key == "acme:identity.resolved"
    assert fields["type"] == "identity.resolved"
    assert fields["tenantId"] == "acme"
    assert fields["traceId"] == "t-1"
    # payload is serialized as a JSON string on the wire
    assert json.loads(fields["payload"]) == {"customerId": "C-1"}


def test_consumer_acks_after_successful_handler():
    client = AsyncMock()
    consumer = BaseConsumer(client, tenant_id="acme", group="uniserve", retry_delay_ms=0)

    handler = AsyncMock()  # succeeds
    ok = _run(consumer.handle_message(
        streams.CHANNEL_MESSAGE_RECEIVED, "5-0", {"payload": {"text": "hi"}}, handler))

    assert ok is True
    handler.assert_awaited_once()
    client.xack.assert_awaited_once_with("acme:channel.message.received", "uniserve", "5-0")
    client.xadd.assert_not_awaited()  # nothing dead-lettered


def test_consumer_sends_to_dlq_after_three_retries():
    client = AsyncMock()
    consumer = BaseConsumer(
        client, tenant_id="acme", group="uniserve", max_retries=3, retry_delay_ms=0)

    handler = AsyncMock(side_effect=RuntimeError("boom"))  # always fails
    ok = _run(consumer.handle_message(
        streams.CHANNEL_MESSAGE_RECEIVED, "6-0", {"payload": {"text": "bad"}}, handler))

    assert ok is False
    assert handler.await_count == 3  # tried 3 times

    # dead-lettered once, to the tenant DLQ, with the original stream + error
    client.xadd.assert_awaited_once()
    dlq_key, dlq_fields = client.xadd.await_args.args
    assert dlq_key == "acme:dlq"
    assert dlq_fields["originalStream"] == "channel.message.received"
    assert dlq_fields["originalMessageId"] == "6-0"
    assert "boom" in dlq_fields["error"]

    # original acked so it leaves the pending list
    client.xack.assert_awaited_once_with("acme:channel.message.received", "uniserve", "6-0")
