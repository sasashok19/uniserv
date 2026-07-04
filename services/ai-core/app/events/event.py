"""The ``BaseEvent`` envelope shared across services (transport only).

Matches the Java ``BaseEvent`` record: ``id``, ``tenantId``, ``type``,
``timestamp`` (ISO-8601), ``traceId`` and a free-form ``payload``. On the wire
the payload is stored as a JSON string so any language can reconstruct it.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


def build_event(
    tenant_id: str,
    type_: str,
    payload: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Build an event envelope, generating ``id``/``timestamp``/``traceId``."""
    return {
        "id": str(uuid.uuid4()),
        "tenantId": tenant_id,
        "type": type_,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "traceId": trace_id or str(uuid.uuid4()),
        "payload": payload or {},
    }


def to_fields(event: dict) -> dict:
    """Flatten an event into Valkey stream fields (payload -> JSON string)."""
    fields = dict(event)
    fields["payload"] = json.dumps(event.get("payload") or {})
    return fields


def from_fields(fields: dict[str, Any]) -> dict:
    """Rebuild an event dict from stream fields (payload JSON -> dict)."""
    event = dict(fields)
    raw = event.get("payload")
    if isinstance(raw, str):
        try:
            event["payload"] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return event
