"""Base publisher for writing events to Valkey Streams (Feature 01)."""

import logging

from app.events.event import to_fields
from app.events.streams import stream_key

logger = logging.getLogger("ai-core")


class BasePublisher:
    """Publishes :func:`app.events.event.build_event` envelopes to Valkey Streams.

    The client is injected so it can be mocked in unit tests and shared in
    production (see :func:`app.events.client.get_valkey`).
    """

    def __init__(self, client, tenant_id: str):
        self._client = client
        self._tenant_id = tenant_id

    async def publish(self, stream: str, event: dict) -> str:
        """Publish an event to the tenant-scoped stream; return the message ID."""
        key = stream_key(self._tenant_id, stream)
        message_id = await self._client.xadd(key, to_fields(event))
        logger.info("published event type=%s stream=%s id=%s", event.get("type"), key, message_id)
        return message_id
