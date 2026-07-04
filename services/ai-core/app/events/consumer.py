"""Base consumer for reading events from Valkey Streams (Feature 01).

Consumer-group semantics: each event is delivered to a group, processed by a
handler, and acknowledged on success. A handler that keeps failing is retried
up to ``max_retries`` times and then routed to the tenant dead-letter queue
(and acked so it leaves the pending list).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.config import settings
from app.events.event import from_fields
from app.events.streams import DLQ, stream_key

logger = logging.getLogger("ai-core")

Handler = Callable[[dict], Awaitable[None]]


class BaseConsumer:
    """Reads from a Valkey stream via a consumer group with retry + DLQ.

    The client is injected so it can be mocked in unit tests and shared in
    production (see :func:`app.events.client.get_valkey`).
    """

    def __init__(
        self,
        client,
        tenant_id: str,
        group: str | None = None,
        max_retries: int | None = None,
        retry_delay_ms: int | None = None,
    ):
        self._client = client
        self._tenant_id = tenant_id
        self._group = group or settings.event_bus_consumer_group
        self._max_retries = max_retries if max_retries is not None else settings.event_bus_max_retries
        self._retry_delay_ms = (
            retry_delay_ms if retry_delay_ms is not None else settings.event_bus_retry_delay_ms
        )

    async def ack(self, stream: str, message_id: str) -> None:
        """Acknowledge a processed message on the tenant-scoped stream."""
        key = stream_key(self._tenant_id, stream)
        await self._client.xack(key, self._group, message_id)

    async def consume(
        self,
        stream: str,
        group: str,
        handler: Handler,
        batch_size: int = 10,
    ) -> int:
        """Read one batch from ``stream`` and process each message.

        Ensures the consumer group exists, reads new messages, and runs each
        through :meth:`handle_message`. Returns the number of messages handled.
        Callers typically invoke this in a loop.
        """
        self._group = group or self._group
        key = stream_key(self._tenant_id, stream)
        await self._ensure_group(key)

        consumer_name = f"{self._group}-consumer"
        response = await self._client.xreadgroup(
            self._group, consumer_name, {key: ">"}, count=batch_size, block=1000
        )

        processed = 0
        for _stream_name, messages in (response or []):
            for message_id, fields in messages:
                await self.handle_message(stream, message_id, from_fields(fields), handler)
                processed += 1
        return processed

    async def handle_message(
        self,
        stream: str,
        message_id: str,
        data: dict,
        handler: Handler,
    ) -> bool:
        """Run the handler with retries; ack on success, DLQ on exhaustion.

        Returns True if the handler succeeded, False if the message was
        dead-lettered after ``max_retries`` attempts.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                await handler(data)
                await self.ack(stream, message_id)
                return True
            except Exception as exc:  # noqa: BLE001 - the whole point is to catch handler failures
                logger.warning(
                    "handler failed stream=%s id=%s attempt=%s/%s: %s",
                    stream, message_id, attempt, self._max_retries, exc,
                )
                if attempt >= self._max_retries:
                    await self._to_dlq(stream, message_id, data, exc)
                    # Ack the original so it leaves the pending list; it now lives in the DLQ.
                    await self.ack(stream, message_id)
                    return False
                if self._retry_delay_ms:
                    await asyncio.sleep(self._retry_delay_ms / 1000)
        return False

    async def _ensure_group(self, key: str) -> None:
        """Create the consumer group (and stream) if it does not already exist."""
        try:
            await self._client.xgroup_create(key, self._group, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001
            if "BUSYGROUP" not in str(exc):
                raise

    async def _to_dlq(self, stream: str, message_id: str, data: dict, error: Exception) -> None:
        """Route a permanently-failed message to the tenant dead-letter queue."""
        dlq_key = stream_key(self._tenant_id, DLQ)
        entry = {
            "originalStream": stream,
            "originalMessageId": message_id,
            "error": str(error),
            "failedAt": datetime.now(timezone.utc).isoformat(),
            "payload": json.dumps(data.get("payload", {})),
        }
        await self._client.xadd(dlq_key, entry)
        logger.error("event dead-lettered stream=%s id=%s error=%s", stream, message_id, error)
