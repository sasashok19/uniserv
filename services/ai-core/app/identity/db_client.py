"""Async HTTP client for the db-writer identity API (Feature 03 → 04)."""

import json
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("ai-core")


class DbWriterClient:
    """Thin wrapper over the db-writer REST API for identity operations.

    Every call optionally carries a ``trace_id`` (the same id assigned to the
    inbound channel message that triggered it), sent as ``X-Trace-Id`` so
    db-writer's request logging can be correlated back to the originating
    transaction — see docs/01_EVENT_BUS.md tracing notes.
    """

    def __init__(self, base_url: str | None = None, internal_key: str | None = None):
        self._base = (base_url or settings.db_writer_url).rstrip("/")
        self._key = internal_key if internal_key is not None else settings.db_writer_internal_api_key

    def _headers(self, trace_id: Optional[str] = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["X-Internal-Key"] = self._key
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        return headers

    async def _request(self, method: str, path: str, trace_id: Optional[str] = None, **kwargs) -> httpx.Response:
        headers = self._headers(trace_id)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.request(method, f"{self._base}{path}", headers=headers, **kwargs)
        if resp.status_code >= 500:
            logger.error("db-writer call failed: %s %s traceId=%s status=%d body=%s",
                         method, path, trace_id, resp.status_code, resp.text[:500])
        elif resp.status_code >= 400:
            logger.warning("db-writer call rejected: %s %s traceId=%s status=%d body=%s",
                           method, path, trace_id, resp.status_code, resp.text[:500])
        else:
            logger.info("db-writer call ok: %s %s traceId=%s status=%d", method, path, trace_id, resp.status_code)
        resp.raise_for_status()
        return resp

    async def find_by_phone(self, tenant_id: str, phone: str, trace_id: Optional[str] = None) -> Optional[dict]:
        return await self._find(tenant_id, {"phone": phone}, trace_id)

    async def find_by_email(self, tenant_id: str, email: str, trace_id: Optional[str] = None) -> Optional[dict]:
        return await self._find(tenant_id, {"email": email}, trace_id)

    async def _find(self, tenant_id: str, params: dict, trace_id: Optional[str] = None) -> Optional[dict]:
        params = {"tenantId": tenant_id, **params}
        resp = await self._request("GET", "/api/v1/db/identities", trace_id, params=params)
        data = resp.json().get("data", [])
        return data[0] if data else None

    async def create_identity(self, payload: dict, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("POST", "/api/v1/db/identities", trace_id, json=payload)
        return resp.json()

    async def get_identity(self, identity_id: str, trace_id: Optional[str] = None) -> Optional[dict]:
        resp = await self._request("GET", f"/api/v1/db/identities/{identity_id}", trace_id)
        return resp.json()

    async def update_identity(self, identity_id: str, payload: dict, trace_id: Optional[str] = None) -> dict:
        """Enrich an existing profile (e.g. add a phone learned via a later
        channel) — never overwrites a field that's already set."""
        resp = await self._request("PATCH", f"/api/v1/db/identities/{identity_id}", trace_id, json=payload)
        return resp.json()

    async def merge_identity(self, keep_id: str, merge_master_id: str, trace_id: Optional[str] = None) -> dict:
        """Merge a duplicate profile into the kept one, reassigning its tickets."""
        resp = await self._request("PATCH", f"/api/v1/db/identities/{keep_id}/merge", trace_id,
                                   json={"mergeMasterId": merge_master_id})
        return resp.json()

    async def anon_ref_exists(self, tenant_id: str, anon_ref_id: str, trace_id: Optional[str] = None) -> bool:
        resp = await self._request("GET", "/api/v1/db/identities/anon-check", trace_id,
                                   params={"tenantId": tenant_id, "anonRefId": anon_ref_id})
        return bool(resp.json().get("exists", False))

    async def enqueue_pending(self, payload: dict, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("POST", "/api/v1/db/identities/pending", trace_id, json=payload)
        return resp.json()

    async def list_tickets(self, tenant_id: str, trace_id: Optional[str] = None, **filters) -> list[dict]:
        params = {"tenantId": tenant_id, **{k: v for k, v in filters.items() if v is not None}}
        resp = await self._request("GET", "/api/v1/db/tickets", trace_id, params=params)
        return resp.json().get("data", [])

    async def create_ticket(self, payload: dict, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("POST", "/api/v1/db/tickets", trace_id, json=payload)
        return resp.json()

    async def update_ticket(self, ticket_id: str, payload: dict, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("PATCH", f"/api/v1/db/tickets/{ticket_id}", trace_id, json=payload)
        return resp.json()

    async def get_ticket(self, ticket_id: str, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("GET", f"/api/v1/db/tickets/{ticket_id}", trace_id)
        return resp.json()

    async def add_message(self, ticket_id: str, payload: dict, trace_id: Optional[str] = None) -> dict:
        resp = await self._request("POST", f"/api/v1/db/tickets/{ticket_id}/messages", trace_id, json=payload)
        return resp.json()

    async def get_messages(self, ticket_id: str, trace_id: Optional[str] = None) -> list[dict]:
        """A ticket's Conversation timeline, oldest first (db-writer's own
        ordering) — used by the status-summary feature to fall back to the
        most recent message when a ticket has no internal notes yet."""
        resp = await self._request("GET", f"/api/v1/db/tickets/{ticket_id}/messages", trace_id)
        return resp.json().get("data", [])

    async def add_event(self, ticket_id: str, payload: dict, trace_id: Optional[str] = None) -> dict:
        """Append an audit-trail entry to a ticket (Feature 22) — used to record
        on the ORIGINAL ticket that another was merged into it as a confirmed
        duplicate. The trail was read-only from here until now."""
        resp = await self._request("POST", f"/api/v1/db/tickets/{ticket_id}/events", trace_id, json=payload)
        return resp.json()

    async def find_message_by_channel_id(
        self, tenant_id: str, channel_message_id: str, trace_id: Optional[str] = None,
    ) -> Optional[dict]:
        """The message a channel provider id belongs to (Feature 24) — routing
        rung 0. Returns None when we never sent/received that id (a 404 here is
        the normal case, not an error: most inbound messages are not replies)."""
        try:
            resp = await self._request(
                "GET", "/api/v1/db/tickets/messages/by-channel-id", trace_id,
                params={"tenantId": tenant_id, "channelMessageId": channel_message_id})
            return resp.json()
        except Exception:  # noqa: BLE001 - a miss is expected; never blocks routing
            return None

    async def set_message_channel_id(
        self, ticket_id: str, message_id: str, channel_message_id: str,
        trace_id: Optional[str] = None,
    ) -> None:
        """Stamp a message we just sent with the provider's id for it
        (Feature 24), so the citizen's reply to it routes back here exactly.
        Best-effort: the citizen already has the message."""
        try:
            await self._request(
                "PATCH", f"/api/v1/db/tickets/{ticket_id}/messages/{message_id}/channel-id",
                trace_id, json={"channelMessageId": channel_message_id})
        except Exception:  # noqa: BLE001 - losing a routing shortcut is not a send failure
            logger.warning("failed to record channel message id traceId=%s ticketId=%s",
                           trace_id, ticket_id)

    async def create_unrouted_message(self, payload: dict, trace_id: Optional[str] = None) -> dict:
        """Park a message routing could not attribute (Feature 24). This is what
        makes "create no ticket" safe: the citizen's words are still stored, and
        a lead can file them against the right ticket."""
        resp = await self._request("POST", "/api/v1/db/unrouted-messages", trace_id, json=payload)
        return resp.json()

    async def unrouted_ask_count(
        self, tenant_id: str, channel_identity_value: str, since: str,
        trace_id: Optional[str] = None,
    ) -> int:
        """How many times we have already asked this contact to clarify since
        `since` (Feature 24) — the difference between asking again and
        escalating. Returns 0 on any failure, i.e. we would rather ask a second
        time than escalate a citizen who was never actually asked."""
        try:
            resp = await self._request(
                "GET", "/api/v1/db/unrouted-messages/ask-count", trace_id,
                params={"tenantId": tenant_id, "channelIdentityValue": channel_identity_value,
                        "since": since})
            return int(resp.json().get("askCount", 0))
        except Exception:  # noqa: BLE001 - see docstring
            logger.warning("failed to read unrouted ask count traceId=%s", trace_id)
            return 0

    async def get_notes(self, ticket_id: str, trace_id: Optional[str] = None) -> list[dict]:
        """A ticket's internal/transition notes, oldest first — the "last
        action taken" for the status-summary feature is the newest of these."""
        resp = await self._request("GET", f"/api/v1/db/tickets/{ticket_id}/notes", trace_id)
        return resp.json().get("data", [])

    async def get_tenant_config(self, tenant_id: str, trace_id: Optional[str] = None) -> dict:
        """Parsed `config_json` for a tenant (Feature 15/16 intake fields,
        categories, SLA) — `{}` on any failure so a config problem never
        blocks the conversation turn itself."""
        try:
            resp = await self._request("GET", f"/api/v1/db/tenants/{tenant_id}", trace_id)
            raw = resp.json().get("config_json")
            return json.loads(raw) if raw else {}
        except Exception as exc:  # noqa: BLE001 - config fetch is best-effort
            logger.warning("failed to load tenant config traceId=%s tenantId=%s error=%s",
                           trace_id, tenant_id, exc)
            return {}
