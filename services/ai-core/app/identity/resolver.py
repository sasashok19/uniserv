"""Identity resolution logic (Feature 03)."""

import json
import logging
import uuid
from typing import Optional

from pydantic import BaseModel

from app.config import settings
from app.events import streams
from app.events.event import build_event
from app.events.publisher import BasePublisher
from app.identity.anon import generate_anon_ref
from app.identity.db_client import DbWriterClient
from app.identity.normalise import normalise_email, normalise_phone

logger = logging.getLogger("ai-core")


class ChannelIdentityIn(BaseModel):
    type: Optional[str] = None
    value: Optional[str] = None
    verified: bool = False


class ResolveRequest(BaseModel):
    tenantId: str
    channel: str
    channelIdentity: ChannelIdentityIn
    threadId: Optional[str] = None
    declaredAnonymous: bool = False
    confirmedEmail: Optional[str] = None
    rawText: Optional[str] = None


class IdentityResolver:
    def __init__(self, db: DbWriterClient, publisher: BasePublisher):
        self._db = db
        self._publisher = publisher

    async def resolve(self, req: ResolveRequest) -> dict:
        # 1. Anonymous declared → mint a unique ANON ref and a fresh profile.
        if req.declaredAnonymous:
            return await self._resolve_anonymous(req)

        # 2. WhatsApp (verified phone) → auto-confirmed match/create by phone.
        if req.channel == "whatsapp" and req.channelIdentity.verified and req.channelIdentity.value:
            return await self._resolve_phone(req)

        # 3. Email with a user-confirmed address → match/create by email.
        if req.confirmedEmail:
            return await self._resolve_confirmed_email(req)

        # 4. Otherwise (e.g. unverified email) → identity gate: pending.
        return await self._resolve_pending(req)

    async def _resolve_anonymous(self, req: ResolveRequest) -> dict:
        anon_ref = await self._unique_anon_ref(req.tenantId)
        master_id = str(uuid.uuid4())
        await self._db.create_identity({
            "tenantId": req.tenantId,
            "masterId": master_id,
            "isAnonymous": True,
            "anonRefId": anon_ref,
            "channelIdsJson": self._channel_ids(req, None),
        })
        await self._emit_resolved(req.tenantId, master_id, "anonymous", is_anonymous=True, anon_ref_id=anon_ref)
        return {
            "masterId": master_id,
            "identityStatus": "anonymous",
            "anonRefId": anon_ref,
            "isNew": True,
        }

    async def _resolve_phone(self, req: ResolveRequest) -> dict:
        phone = normalise_phone(req.channelIdentity.value)
        existing = await self._db.find_by_phone(req.tenantId, phone)
        if existing:
            master_id = existing["master_id"]
            await self._emit_resolved(req.tenantId, master_id, "confirmed")
            return {"masterId": master_id, "identityStatus": "confirmed", "isNew": False}

        master_id = str(uuid.uuid4())
        await self._db.create_identity({
            "tenantId": req.tenantId,
            "masterId": master_id,
            "phone": phone,
            "channelIdsJson": self._channel_ids(req, phone),
        })
        await self._emit_resolved(req.tenantId, master_id, "confirmed")
        return {"masterId": master_id, "identityStatus": "confirmed", "isNew": True}

    async def _resolve_confirmed_email(self, req: ResolveRequest) -> dict:
        email = normalise_email(req.confirmedEmail)
        existing = await self._db.find_by_email(req.tenantId, email)
        if existing:
            master_id = existing["master_id"]
            await self._emit_resolved(req.tenantId, master_id, "confirmed")
            return {"masterId": master_id, "identityStatus": "confirmed", "merged": False, "isNew": False}

        master_id = str(uuid.uuid4())
        await self._db.create_identity({
            "tenantId": req.tenantId,
            "masterId": master_id,
            "email": email,
            "channelIdsJson": self._channel_ids(req, email),
        })
        await self._emit_resolved(req.tenantId, master_id, "confirmed")
        return {"masterId": master_id, "identityStatus": "confirmed", "merged": False, "isNew": True}

    async def _resolve_pending(self, req: ResolveRequest) -> dict:
        await self._db.enqueue_pending({
            "tenantId": req.tenantId,
            "threadId": req.threadId or str(uuid.uuid4()),
            "channel": req.channel,
            "channelIdentityValue": req.channelIdentity.value,
            "rawMessage": req.rawText,
            "timeoutHours": settings.identity_pending_timeout_hours,
        })
        # Signal the AI pipeline that an identity confirmation is needed.
        event = build_event(req.tenantId, "identity.pending", {
            "threadId": req.threadId,
            "channel": req.channel,
        })
        await self._publisher.publish(streams.IDENTITY_PENDING, event)
        return {"identityStatus": "pending", "threadId": req.threadId}

    async def _unique_anon_ref(self, tenant_id: str) -> str:
        prefix = settings.identity_anon_ref_prefix
        for _ in range(20):
            ref = generate_anon_ref(prefix)
            if not await self._db.anon_ref_exists(tenant_id, ref):
                return ref
        # Extremely unlikely; fall back to a longer suffix via uuid.
        return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"

    async def _emit_resolved(self, tenant_id: str, master_id: str, identity_status: str,
                             is_anonymous: bool = False, anon_ref_id: Optional[str] = None) -> None:
        event = build_event(tenant_id, "identity.resolved", {
            "masterId": master_id,
            "identityStatus": identity_status,
            "isAnonymous": is_anonymous,
            "anonRefId": anon_ref_id,
        })
        await self._publisher.publish(streams.IDENTITY_RESOLVED, event)

    @staticmethod
    def _channel_ids(req: ResolveRequest, value: Optional[str]) -> str:
        return json.dumps([{
            "channel": req.channel,
            "value": value or req.channelIdentity.value,
            "verified": req.channelIdentity.verified,
        }])
