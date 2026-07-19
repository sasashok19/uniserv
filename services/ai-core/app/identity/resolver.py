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


def _safe_email(value: Optional[str]) -> Optional[str]:
    """normalise_email that returns None instead of raising when the value
    isn't a valid email. Callers here receive identity values that can come
    from an LLM tool call (assistant path), where the model may hand a phone
    number to an email-typed field — a bad value must degrade to "no email",
    not crash the whole identity-resolution turn."""
    if not value:
        return None
    try:
        return normalise_email(value)
    except ValueError:
        return None


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
    # A citizen-provided mobile number (e.g. from the email intake form) —
    # takes priority over confirmedEmail so the same person is recognised by
    # phone across channels, matching how a verified WhatsApp number already
    # resolves. confirmedName is stored alongside it when creating a new
    # profile (not currently updated on an existing match).
    confirmedPhone: Optional[str] = None
    confirmedName: Optional[str] = None
    rawText: Optional[str] = None
    # Correlation id for the whole transaction (set by the adapter that first
    # received the message); threaded through db-writer calls and every event
    # emitted here so the resolution outcome can be traced back to its origin.
    traceId: Optional[str] = None


class IdentityResolver:
    def __init__(self, db: DbWriterClient, publisher: BasePublisher):
        self._db = db
        self._publisher = publisher

    async def resolve(self, req: ResolveRequest) -> dict:
        logger.info("identity resolve start traceId=%s tenantId=%s channel=%s declaredAnonymous=%s",
                    req.traceId, req.tenantId, req.channel, req.declaredAnonymous)
        # 1. Anonymous declared → mint a unique ANON ref and a fresh profile.
        if req.declaredAnonymous:
            return await self._resolve_anonymous(req)

        # 2. A citizen-provided mobile (e.g. email intake form) → match/create
        #    by phone, same as WhatsApp — phone is the cross-channel key.
        if req.confirmedPhone:
            return await self._resolve_phone(req, req.confirmedPhone)

        # 3. WhatsApp (verified phone) → auto-confirmed match/create by phone.
        if req.channel == "whatsapp" and req.channelIdentity.verified and req.channelIdentity.value:
            return await self._resolve_phone(req, req.channelIdentity.value)

        # 4. Email with a user-confirmed address → match/create by email.
        if req.confirmedEmail:
            return await self._resolve_confirmed_email(req)

        # 5. Otherwise (e.g. unverified email) → identity gate: pending.
        return await self._resolve_pending(req)

    async def _resolve_anonymous(self, req: ResolveRequest) -> dict:
        anon_ref = await self._unique_anon_ref(req.tenantId, req.traceId)
        master_id = str(uuid.uuid4())
        await self._db.create_identity({
            "tenantId": req.tenantId,
            "masterId": master_id,
            "isAnonymous": True,
            "anonRefId": anon_ref,
            "channelIdsJson": self._channel_ids(req, None),
        }, trace_id=req.traceId)
        await self._emit_resolved(req.tenantId, master_id, "anonymous",
                                  trace_id=req.traceId, is_anonymous=True, anon_ref_id=anon_ref)
        logger.info("identity resolved traceId=%s tenantId=%s masterId=%s status=anonymous anonRefId=%s isNew=True",
                    req.traceId, req.tenantId, master_id, anon_ref)
        return {
            "masterId": master_id,
            "identityStatus": "anonymous",
            "anonRefId": anon_ref,
            "isNew": True,
        }

    async def _resolve_phone(self, req: ResolveRequest, phone_value: str) -> dict:
        phone = normalise_phone(phone_value)
        # The email-channel's native address is only a usable cross-channel key
        # when the channel identity really IS an email. On the assistant path
        # the model can call confirm_identity with a phone value on an
        # email-origin thread (req.channel stays "email" but the identity type
        # becomes "phone"), so guard on the identity TYPE — not the channel —
        # and tolerate a non-email value via _safe_email rather than crashing
        # the whole turn in normalise_email.
        native_email = _safe_email(req.channelIdentity.value) if req.channelIdentity.type == "email" else None
        # A citizen-PROVIDED email (Feature 15/16 — e.g. a WhatsApp user
        # asked for their email as part of the configurable intake fields)
        # is just as good a cross-channel key as a native one; without this,
        # an email actively solicited from a WhatsApp citizen would be
        # silently ignored for enrichment/merge purposes.
        provided_email = native_email or _safe_email(req.confirmedEmail)
        existing_by_phone = await self._db.find_by_phone(req.tenantId, phone, trace_id=req.traceId)

        if existing_by_phone:
            master_id = existing_by_phone["master_id"]
            # Cross-channel merge: this request also carries an email
            # (native or citizen-provided) that already belongs to a
            # SEPARATE, independently-created identity (e.g. emailed in
            # once before ever giving a phone, and separately WhatsApp'd
            # in) — same person, two records so far; combine them (moves
            # the older one's tickets onto this one).
            if provided_email:
                other = await self._db.find_by_email(req.tenantId, provided_email, trace_id=req.traceId)
                if other and other["master_id"] != master_id:
                    await self._db.merge_identity(existing_by_phone["id"], other["master_id"], trace_id=req.traceId)
                    logger.info(
                        "identities merged traceId=%s tenantId=%s keptMasterId=%s mergedMasterId=%s",
                        req.traceId, req.tenantId, master_id, other["master_id"])
            await self._emit_resolved(req.tenantId, master_id, "confirmed", trace_id=req.traceId)
            logger.info("identity resolved traceId=%s tenantId=%s masterId=%s status=confirmed isNew=False",
                        req.traceId, req.tenantId, master_id)
            return {"masterId": master_id, "identityStatus": "confirmed", "isNew": False}

        # Not found by phone — before creating fresh, check whether the
        # email (native, or citizen-provided via intake) already has a
        # record from an earlier interaction; enrich it with the phone
        # instead of creating a duplicate for the same person.
        existing_by_email = (
            await self._db.find_by_email(req.tenantId, provided_email, trace_id=req.traceId)
            if provided_email else None
        )
        if existing_by_email:
            master_id = existing_by_email["master_id"]
            enrichment = {"phone": phone}
            if req.confirmedName:
                enrichment["name"] = req.confirmedName
            await self._db.update_identity(existing_by_email["id"], enrichment, trace_id=req.traceId)
            await self._emit_resolved(req.tenantId, master_id, "confirmed", trace_id=req.traceId)
            logger.info("identity enriched with phone traceId=%s tenantId=%s masterId=%s",
                        req.traceId, req.tenantId, master_id)
            return {"masterId": master_id, "identityStatus": "confirmed", "isNew": False}

        master_id = str(uuid.uuid4())
        payload = {
            "tenantId": req.tenantId,
            "masterId": master_id,
            "phone": phone,
            "channelIdsJson": self._channel_ids(req, phone),
        }
        if req.confirmedName:
            payload["name"] = req.confirmedName
        if provided_email:
            payload["email"] = provided_email
        await self._db.create_identity(payload, trace_id=req.traceId)
        await self._emit_resolved(req.tenantId, master_id, "confirmed", trace_id=req.traceId)
        logger.info("identity resolved traceId=%s tenantId=%s masterId=%s status=confirmed isNew=True",
                    req.traceId, req.tenantId, master_id)
        return {"masterId": master_id, "identityStatus": "confirmed", "isNew": True}

    async def _resolve_confirmed_email(self, req: ResolveRequest) -> dict:
        email = normalise_email(req.confirmedEmail)
        existing = await self._db.find_by_email(req.tenantId, email, trace_id=req.traceId)
        if existing:
            master_id = existing["master_id"]
            await self._emit_resolved(req.tenantId, master_id, "confirmed", trace_id=req.traceId)
            logger.info(
                "identity resolved traceId=%s tenantId=%s masterId=%s status=confirmed merged=False isNew=False",
                req.traceId, req.tenantId, master_id)
            return {"masterId": master_id, "identityStatus": "confirmed", "merged": False, "isNew": False}

        master_id = str(uuid.uuid4())
        payload = {
            "tenantId": req.tenantId,
            "masterId": master_id,
            "email": email,
            "channelIdsJson": self._channel_ids(req, email),
        }
        if req.confirmedName:
            payload["name"] = req.confirmedName
        await self._db.create_identity(payload, trace_id=req.traceId)
        await self._emit_resolved(req.tenantId, master_id, "confirmed", trace_id=req.traceId)
        logger.info(
            "identity resolved traceId=%s tenantId=%s masterId=%s status=confirmed merged=False isNew=True",
            req.traceId, req.tenantId, master_id)
        return {"masterId": master_id, "identityStatus": "confirmed", "merged": False, "isNew": True}

    async def _resolve_pending(self, req: ResolveRequest) -> dict:
        await self._db.enqueue_pending({
            "tenantId": req.tenantId,
            "threadId": req.threadId or str(uuid.uuid4()),
            "channel": req.channel,
            "channelIdentityValue": req.channelIdentity.value,
            "rawMessage": req.rawText,
            "timeoutHours": settings.identity_pending_timeout_hours,
        }, trace_id=req.traceId)
        # Signal the AI pipeline that an identity confirmation is needed.
        event = build_event(req.tenantId, "identity.pending", {
            "threadId": req.threadId,
            "channel": req.channel,
        }, trace_id=req.traceId)
        await self._publisher.publish(streams.IDENTITY_PENDING, event)
        logger.info("identity pending traceId=%s tenantId=%s threadId=%s channel=%s",
                    req.traceId, req.tenantId, req.threadId, req.channel)
        return {"identityStatus": "pending", "threadId": req.threadId}

    async def _unique_anon_ref(self, tenant_id: str, trace_id: Optional[str] = None) -> str:
        prefix = settings.identity_anon_ref_prefix
        for _ in range(20):
            ref = generate_anon_ref(prefix)
            if not await self._db.anon_ref_exists(tenant_id, ref, trace_id=trace_id):
                return ref
        # Extremely unlikely; fall back to a longer suffix via uuid.
        return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"

    async def _emit_resolved(self, tenant_id: str, master_id: str, identity_status: str,
                             trace_id: Optional[str] = None,
                             is_anonymous: bool = False, anon_ref_id: Optional[str] = None) -> None:
        event = build_event(tenant_id, "identity.resolved", {
            "masterId": master_id,
            "identityStatus": identity_status,
            "isAnonymous": is_anonymous,
            "anonRefId": anon_ref_id,
        }, trace_id=trace_id)
        await self._publisher.publish(streams.IDENTITY_RESOLVED, event)

    @staticmethod
    def _channel_ids(req: ResolveRequest, value: Optional[str]) -> str:
        return json.dumps([{
            "channel": req.channel,
            "value": value or req.channelIdentity.value,
            "verified": req.channelIdentity.verified,
        }])
