"""Logical event-bus stream names and the tenant-scoped key helper.

Mirrors the Java ``EventStreams`` catalogue in api-gateway so both sides agree
on stream names. On the wire every stream is namespaced per tenant as
``"{tenant}:{stream}"``.
"""

CHANNEL_MESSAGE_RECEIVED = "channel.message.received"
IDENTITY_RESOLVED = "identity.resolved"
# Identity sub-events (Feature 03): not part of the core transport catalogue below.
IDENTITY_PENDING = "identity.pending"
IDENTITY_MERGED = "identity.merged"
COMPLAINT_READY = "complaint.ready"
TICKET_CREATED = "ticket.created"
TICKET_UPDATED = "ticket.updated"
AI_REPLY_SEND = "ai.reply.send"
DLQ = "dlq"

# All logical stream names managed by the event bus.
ALL = [
    CHANNEL_MESSAGE_RECEIVED,
    IDENTITY_RESOLVED,
    COMPLAINT_READY,
    TICKET_CREATED,
    TICKET_UPDATED,
    AI_REPLY_SEND,
    DLQ,
]


def stream_key(tenant_id: str, stream: str) -> str:
    """Build the tenant-scoped stream key: ``"{tenant_id}:{stream}"``."""
    return f"{tenant_id}:{stream}"
