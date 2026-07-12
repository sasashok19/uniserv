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
from app.identity.db_client import DbWriterClient
from app.notifications.sender import deliver_reply, send_ticket_ack_email
from app.tickets.intake import ensure_ticket_stub
from app.tickets.service import create_ticket_from_complaint

logger = logging.getLogger("ai-core")


async def _handle_channel_message(tenant_id: str, event: dict) -> None:
    trace_id = event.get("traceId")
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
        subject=payload.get("subject"),
        traceId=trace_id,
    )
    thread_key = ConversationAgent._thread_key(req)
    logger.info(
        "channel.message.received received traceId=%s tenantId=%s channel=%s threadId=%s",
        trace_id, tenant_id, req.channel, thread_key,
    )
    # Feature 12/15: a ticket exists from the very first message, not only
    # once identity is confirmed — see app/tickets/intake.py. A subject-line
    # ticket reference (email only) takes priority over thread matching.
    stub = await ensure_ticket_stub(
        DbWriterClient(), tenant_id, thread_key, req.channel, subject=req.subject, trace_id=trace_id)
    req.ticketId = stub["id"]
    req.ticketNumber = stub.get("ticketNumber")
    try:
        result = await ConversationAgent(tenant_id).process(req)
    except Exception:
        logger.exception(
            "channel.message.received processing failed traceId=%s tenantId=%s threadId=%s",
            trace_id, tenant_id, ConversationAgent._thread_key(req),
        )
        raise
    logger.info(
        "processed channel.message.received traceId=%s threadId=%s result=%s",
        trace_id, ConversationAgent._thread_key(req), result,
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


async def _handle_complaint_ready(tenant_id: str, event: dict) -> None:
    trace_id = event.get("traceId")
    payload = event.get("payload") or {}
    logger.info(
        "complaint.ready received traceId=%s tenantId=%s threadId=%s",
        trace_id, tenant_id, payload.get("threadId"),
    )
    db = DbWriterClient()
    try:
        result = await create_ticket_from_complaint(db, tenant_id, payload, trace_id=trace_id)
    except Exception:
        logger.exception(
            "complaint.ready processing failed traceId=%s tenantId=%s threadId=%s",
            trace_id, tenant_id, payload.get("threadId"),
        )
        raise
    logger.info("complaint.ready processed traceId=%s result=%s", trace_id, result)

    try:
        await send_ticket_ack_email(
            channel=payload.get("channel"),
            to_address=payload.get("channelIdentityValue"),
            ticket_number=result.get("ticketNumber"),
            category=result.get("category"),
            status=result.get("status"),
            is_duplicate=result.get("action") == "append_to_existing",
            trace_id=trace_id,
        )
    except Exception:  # noqa: BLE001 - the ticket itself is already saved; a failed ack email must not roll it back
        logger.exception("ticket ack email failed traceId=%s ticketId=%s", trace_id, result.get("ticketId"))


async def run_complaint_ready_consumer(client, tenant_id: str, stop_event: asyncio.Event) -> None:
    """Long-poll `complaint.ready` for `tenant_id` until `stop_event` is set."""
    consumer = BaseConsumer(client, tenant_id)
    group = settings.event_bus_consumer_group
    logger.info("complaint.ready consumer starting tenant=%s group=%s", tenant_id, group)

    async def handler(event: dict) -> None:
        await _handle_complaint_ready(tenant_id, event)

    while not stop_event.is_set():
        try:
            await consumer.consume(streams.COMPLAINT_READY, group, handler)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive across transient Valkey errors
            logger.exception("complaint.ready consumer loop error; retrying in 1s")
            await asyncio.sleep(1)


async def _handle_ai_reply_send(tenant_id: str, event: dict) -> None:
    trace_id = event.get("traceId")
    payload = event.get("payload") or {}
    logger.info(
        "ai.reply.send received traceId=%s tenantId=%s channel=%s threadId=%s",
        trace_id, tenant_id, payload.get("channel"), payload.get("threadId"),
    )
    try:
        result = await deliver_reply(payload, trace_id=trace_id)
    except Exception:
        logger.exception(
            "ai.reply.send delivery failed traceId=%s tenantId=%s threadId=%s",
            trace_id, tenant_id, payload.get("threadId"),
        )
        raise
    logger.info("ai.reply.send processed traceId=%s result=%s", trace_id, result)


async def run_ai_reply_send_consumer(client, tenant_id: str, stop_event: asyncio.Event) -> None:
    """Long-poll `ai.reply.send` for `tenant_id` until `stop_event` is set."""
    consumer = BaseConsumer(client, tenant_id)
    group = settings.event_bus_consumer_group
    logger.info("ai.reply.send consumer starting tenant=%s group=%s", tenant_id, group)

    async def handler(event: dict) -> None:
        await _handle_ai_reply_send(tenant_id, event)

    while not stop_event.is_set():
        try:
            await consumer.consume(streams.AI_REPLY_SEND, group, handler)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive across transient Valkey errors
            logger.exception("ai.reply.send consumer loop error; retrying in 1s")
            await asyncio.sleep(1)
