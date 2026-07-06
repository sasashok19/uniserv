"""Live event-bus wiring: consumes `channel.message.received` into the
conversation agent (Feature 01 x 06).

Runs as a background task for the lifetime of the app (see ``app.main``'s
lifespan). Uses the same :class:`~app.events.consumer.BaseConsumer` primitives
already covered by the Feature 01 unit/integration tests — this module just
supplies the production handler and the run loop.
"""

import asyncio
import logging

from app.config import settings
from app.conversation.agent import ChannelIdentityIn, ConversationAgent, TestEventRequest
from app.events import streams
from app.events.consumer import BaseConsumer

logger = logging.getLogger("ai-core")


async def _handle_channel_message(tenant_id: str, event: dict) -> None:
    payload = event.get("payload") or {}
    identity = payload.get("channelIdentity") or {}
    req = TestEventRequest(
        tenantId=tenant_id,
        channel=payload.get("channel", "unknown"),
        channelIdentity=ChannelIdentityIn(
            type=identity.get("type"),
            value=identity.get("value"),
            verified=bool(identity.get("verified", False)),
        ),
        rawText=payload.get("rawText") or "",
        threadId=payload.get("threadId"),
    )
    result = await ConversationAgent(tenant_id).process(req)
    logger.info(
        "processed channel.message.received traceId=%s threadId=%s result=%s",
        event.get("traceId"), ConversationAgent._thread_key(req), result,
    )


async def run_channel_message_consumer(client, tenant_id: str, stop_event: asyncio.Event) -> None:
    """Long-poll `channel.message.received` for `tenant_id` until `stop_event` is set."""
    consumer = BaseConsumer(client, tenant_id)
    group = settings.event_bus_consumer_group
    logger.info("channel.message.received consumer starting tenant=%s group=%s", tenant_id, group)

    async def handler(event: dict) -> None:
        await _handle_channel_message(tenant_id, event)

    while not stop_event.is_set():
        try:
            await consumer.consume(streams.CHANNEL_MESSAGE_RECEIVED, group, handler)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive across transient Valkey errors
            logger.exception("channel.message.received consumer loop error; retrying in 1s")
            await asyncio.sleep(1)
