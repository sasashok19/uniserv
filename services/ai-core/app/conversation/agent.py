"""Conversation agent orchestration (Feature 06): identity gate + info gathering.

Two execution paths:
- ``_process_via_assistant``: OpenAI Assistants API (threads/runs + tool calls)
  when ``OPENAI_API_KEY``/``OPENAI_ASSISTANT_ID`` are configured. Falls back to
  the rule-based path on any failure (graceful degradation).
- ``_process_rule_based``: the Phase-1 dev fallback used when no LLM is
  configured (see ``/api/v1/internal/test-llm-health``).
"""

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel

from app.classify.classifier import classify
from app.config import settings
from app.conversation.openai_gateway import OpenAIAssistantGateway
from app.events import streams
from app.events.client import get_valkey
from app.events.event import build_event
from app.events.publisher import BasePublisher
from app.identity.db_client import DbWriterClient
from app.identity.resolver import ChannelIdentityIn as ResolverChannelIdentityIn
from app.identity.resolver import IdentityResolver, ResolveRequest
from app.tickets.intake import update_ticket_identity

logger = logging.getLogger("ai-core")

IDENTITY_REQUEST_MESSAGE = (
    "Thanks for reaching out. To register your complaint, please reply with "
    "the following details:\n\n"
    "1. Name:\n"
    "2. Mobile Number (10 digits):\n"
    "3. Service/Customer ID (if available):\n"
    "4. Area Pin Code (if available, 6 digits):\n\n"
    "If we don't hear back within 14 days, this request will be automatically closed."
)

FOLLOWUP_QUESTION = (
    "Thanks for reaching out. Could you tell us a bit more about what went wrong "
    "so we can help — for example the service affected and what happened?"
)

# Rule-based fallback only (no LLM to interpret a free-text reply). Identity
# is confirmed by "anonymous", or by Name + a contact method — a mobile
# number in the reply, or (for email) the native from-address, which is
# already known without asking. So Name is the only field that actually
# blocks the gate; Mobile/Service ID/Pin Code are extracted best-effort and
# only checked for FORMAT (not presence) when supplied. Each field is
# extracted by its label, tolerant of a ":"/"-"/"is" separator or none at
# all. The mobile/pincode capture bounds are deliberately wide enough to also
# catch too-short/too-long values — so a badly-formatted number is reported
# as "invalid", not silently treated as "missing".
# A self-typed value with no label isn't handled here (that needs real NLU —
# see the OpenAI assistant path's confirm_identity tool).
_ANONYMOUS_REPLY_RE = re.compile(r"\banonymous\b", re.IGNORECASE)
_SEP = r"(?:\s*(?:is\b|[:=\-])\s*)?"
_SERVICE_ID_RE = re.compile(rf"(?:service|customer)[\s/]*id{_SEP}([A-Za-z0-9\-]{{2,20}})", re.IGNORECASE)
_MOBILE_RE = re.compile(rf"mobile(?:\s*number)?\s*(?:\([^)]*\))?{_SEP}(\+?[\d\s\-]{{4,15}})", re.IGNORECASE)
_NAME_RE = re.compile(rf"\bname{_SEP}([A-Za-z][A-Za-z .]{{1,60}})", re.IGNORECASE)
_PINCODE_RE = re.compile(rf"(?:area\s*)?pin\s*code\s*(?:\([^)]*\))?{_SEP}([\d\s\-]{{4,10}})", re.IGNORECASE)

_INTAKE_FIELD_LABELS = {
    "serviceId": "Service/Customer ID",
    "mobile": "Mobile Number (10 digits)",
    "name": "Name",
    "pinCode": "Area Pin Code (6 digits)",
}


def _digits_only(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def _extract_intake_fields(text: str) -> dict:
    """Best-effort extraction of the four intake fields from a labeled reply."""
    text = text or ""
    service_id_match = _SERVICE_ID_RE.search(text)
    mobile_match = _MOBILE_RE.search(text)
    name_match = _NAME_RE.search(text)
    pincode_match = _PINCODE_RE.search(text)

    mobile_digits = _digits_only(mobile_match.group(1)) if mobile_match else None
    pincode_digits = _digits_only(pincode_match.group(1)) if pincode_match else None

    return {
        "serviceId": service_id_match.group(1).strip() if service_id_match else None,
        "mobile": mobile_digits or None,
        "mobileValid": bool(mobile_digits) and len(mobile_digits) == 10,
        "name": name_match.group(1).strip() if name_match else None,
        "pinCode": pincode_digits or None,
        "pinCodeValid": bool(pincode_digits) and len(pincode_digits) == 6,
    }


def _missing_intake_fields(intake: dict) -> list[str]:
    """Human-readable list of what's missing or invalid, empty when complete.

    Name is the only field that's actually required to block the gate — a
    contact method is satisfied by Mobile (if supplied) or by the native
    channel address, which is already known for email without asking.
    Service ID / Pin Code are best-effort only. Mobile/Pin Code are still
    flagged if supplied but malformed, since accepting a garbled number
    would be worse than asking once more.
    """
    missing = []
    if not intake["name"]:
        missing.append(_INTAKE_FIELD_LABELS["name"])
    if intake["mobile"] is not None and not intake["mobileValid"]:
        missing.append("a valid 10-digit Mobile Number (the one you sent isn't 10 digits)")
    if intake["pinCode"] is not None and not intake["pinCodeValid"]:
        missing.append("a valid 6-digit Area Pin Code (the one you sent isn't 6 digits)")
    return missing


def _followup_missing_message(missing: list[str]) -> str:
    bullets = "\n".join(f"- {item}" for item in missing)
    return f"Thanks for the details. We still need:\n{bullets}"


class ChannelIdentityIn(BaseModel):
    type: Optional[str] = None
    value: Optional[str] = None
    verified: bool = False


class TestEventRequest(BaseModel):
    tenantId: str
    channel: str
    channelIdentity: ChannelIdentityIn
    rawText: str = ""
    threadId: Optional[str] = None
    declaredAnonymous: bool = False
    # Correlation id assigned by the originating channel adapter — carried
    # through every downstream event/log line for this transaction.
    traceId: Optional[str] = None
    # The ticket stub already created for this thread (Feature 12) — set by
    # dispatcher.py before process() is called for the live pipeline; absent
    # for direct test-endpoint calls, which skip stub tracking entirely.
    ticketId: Optional[str] = None
    # Human-facing ticket number for the same stub (e.g. "TKT-00042") — set
    # alongside ticketId so outbound replies can embed it in the subject
    # line (Feature 15); citizens replying to that subject let
    # ensure_ticket_stub route the reply straight back to this ticket.
    ticketNumber: Optional[str] = None
    # Email subject line of the inbound message, when the channel has one
    # (Feature 15) — used to detect a ticket number the citizen replied to.
    subject: Optional[str] = None


class ConversationAgent:
    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id
        self._publisher = BasePublisher(get_valkey(), tenant_id)
        self._db = DbWriterClient()
        self._openai = OpenAIAssistantGateway()

    async def process(self, req: TestEventRequest) -> dict:
        logger.info("conversation turn start traceId=%s tenantId=%s channel=%s threadId=%s",
                    req.traceId, req.tenantId, req.channel, req.threadId)
        if self._openai.is_available():
            try:
                return await self._process_via_assistant(req)
            except Exception:  # noqa: BLE001 - graceful degradation to rule-based
                logger.exception("OpenAI assistant turn failed traceId=%s; falling back to rule-based pipeline",
                                 req.traceId)
        return await self._process_rule_based(req)

    # ------------------------------------------------------------------
    # Rule-based fallback (Phase 1 dev default — no LLM key configured)
    # ------------------------------------------------------------------

    async def _process_rule_based(self, req: TestEventRequest) -> dict:
        thread_key = self._thread_key(req)
        # No conversation memory across turns here (unlike the assistant
        # path) except this one saved field: the intake form is a SEPARATE
        # reply from the complaint description, so once identity is
        # confirmed we need to recall what the citizen originally wrote
        # rather than classify the intake reply itself.
        state = await self._load_state(thread_key) or {}

        # --- Identity gate ---
        declared_anonymous = req.declaredAnonymous or bool(_ANONYMOUS_REPLY_RE.search(req.rawText or ""))
        intake = None
        summary_source = req.rawText
        master_id = None

        if req.channelIdentity.verified or declared_anonymous:
            master_id = await self._resolve_master_id(req, declared_anonymous)
        else:
            known = await self._find_known_identity(req)
            if known:
                # Returning citizen on this same email/phone with a name
                # already on file — no need to ask again.
                master_id = known["masterId"]
            else:
                intake = _extract_intake_fields(req.rawText)
                missing = _missing_intake_fields(intake)
                if missing:
                    original_text = state.get("original_raw_text") or req.rawText
                    is_first_ask = not state.get("original_raw_text")
                    message = IDENTITY_REQUEST_MESSAGE if is_first_ask else _followup_missing_message(missing)
                    logger.info("identity gate: requesting identity traceId=%s threadId=%s missing=%s",
                                req.traceId, thread_key, missing)
                    await self._send_reply(req, thread_key, message, is_identity_request=True)
                    await self._save_state(thread_key, {
                        "identity_status": "pending",
                        "questions_asked": 0,
                        "original_raw_text": original_text,
                    })
                    return {
                        "identityStatus": "pending",
                        "identityRequestSent": True,
                        "complaintReady": False,
                    }
                # Name (+ optionally a valid mobile) present — gate passes.
                # This reply is the intake form, not the complaint
                # description; use whatever we captured on the first
                # (pending) message instead.
                summary_source = state.get("original_raw_text") or req.rawText
                master_id = await self._resolve_master_id(req, declared_anonymous=False, intake=intake)

        identity_status = "anonymous" if declared_anonymous else "confirmed"

        # Reflect identity onto the stub ticket immediately (Feature 12) —
        # this is what moves it out of the Unconfirmed queue as soon as
        # identity resolves, independent of whether the complaint itself is
        # ready yet (e.g. a still-vague complaint on this same turn).
        if req.ticketId:
            await update_ticket_identity(self._db, req.ticketId, master_id, identity_status, trace_id=req.traceId)

        # --- Info gathering ---
        summary = (summary_source or "").strip()
        classification = classify(summary)
        category_hint = classification["category"]
        vague = category_hint == "other" or len(summary.split()) < 4

        if vague and settings.ai_max_followup_questions >= 1:
            questions_asked = 1
            logger.info("info gathering: vague complaint, asking follow-up traceId=%s threadId=%s",
                        req.traceId, thread_key)
            await self._send_reply(req, thread_key, FOLLOWUP_QUESTION)
            complaint_ready = False
        else:
            questions_asked = 0
            complaint_ready = True

        extracted = {"complaint_summary": summary, "category_hint": category_hint}
        if intake:
            extracted["intake"] = intake

        if complaint_ready:
            logger.info("complaint ready traceId=%s threadId=%s identityStatus=%s category=%s masterId=%s",
                        req.traceId, thread_key, identity_status, category_hint, master_id)
            await self._publisher.publish(streams.COMPLAINT_READY, build_event(
                self._tenant_id, "complaint.ready", {
                    "threadId": thread_key,
                    "ticketId": req.ticketId,
                    "identityStatus": identity_status,
                    "masterId": master_id,
                    "channel": req.channel,
                    "channelIdentityValue": req.channelIdentity.value,
                    "extractedFields": extracted,
                }, trace_id=req.traceId))

        await self._save_state(thread_key, {
            "identity_status": identity_status,
            "extracted_fields": extracted,
            "questions_asked": questions_asked,
        })

        return {
            "identityStatus": identity_status,
            "questionsAsked": questions_asked,
            "complaintReady": complaint_ready,
            "extractedFields": extracted,
        }

    async def _find_known_identity(self, req: TestEventRequest) -> Optional[dict]:
        """Skip the intake ask entirely for a returning citizen: same email or
        phone seen before, with a name already on file."""
        value = req.channelIdentity.value
        if not value:
            return None
        if req.channelIdentity.type == "email":
            existing = await self._db.find_by_email(req.tenantId, value, trace_id=req.traceId)
        elif req.channelIdentity.type == "phone":
            existing = await self._db.find_by_phone(req.tenantId, value, trace_id=req.traceId)
        else:
            existing = None
        if existing and existing.get("name"):
            return {"masterId": existing.get("master_id")}
        return None

    async def _resolve_master_id(
        self, req: TestEventRequest, declared_anonymous: bool, intake: Optional[dict] = None,
    ) -> Optional[str]:
        """Resolve (or create) the citizen's identity profile. Idempotent for
        confirmed phone/email (find-or-create by value), so calling this more
        than once per thread (e.g. once when the gate passes, again if a
        later turn re-derives it) is safe — the anonymous path's
        fresh-ref-per-call behaviour is an accepted Phase-1 simplification.
        """
        native_email = req.channelIdentity.value if req.channelIdentity.type == "email" else None
        confirmed_phone = intake.get("mobile") if intake and intake.get("mobileValid") else None
        confirmed_name = intake.get("name") if intake else None
        resolve_req = ResolveRequest(
            tenantId=req.tenantId,
            channel=req.channel,
            channelIdentity=ResolverChannelIdentityIn(
                type=req.channelIdentity.type, value=req.channelIdentity.value, verified=req.channelIdentity.verified,
            ),
            threadId=req.threadId,
            declaredAnonymous=declared_anonymous,
            confirmedPhone=confirmed_phone,
            confirmedEmail=native_email if not declared_anonymous else None,
            confirmedName=confirmed_name,
            rawText=req.rawText,
            traceId=req.traceId,
        )
        resolver = IdentityResolver(self._db, self._publisher)
        result = await resolver.resolve(resolve_req)
        return result.get("masterId")

    # ------------------------------------------------------------------
    # OpenAI Assistants API path
    # ------------------------------------------------------------------

    async def _process_via_assistant(self, req: TestEventRequest) -> dict:
        thread_key = self._thread_key(req)
        state = await self._load_state(thread_key) or {
            "identity_status": "pending",
            "master_id": None,
            "extracted_fields": {},
            "questions_asked": 0,
            "complaint_ready": False,
        }

        user_message = self._render_user_message(req)
        additional_instructions = self._render_additional_instructions(req, state)

        async def execute_tool(name: str, args: dict) -> dict:
            if name == "confirm_identity":
                return await self._tool_confirm_identity(req, state, args)
            if name == "submit_complaint":
                return await self._tool_submit_complaint(req, thread_key, state, args)
            return {"error": f"unknown tool '{name}'"}

        reply_text = await self._openai.run_turn(
            self._tenant_id, thread_key, user_message, execute_tool, additional_instructions,
        )

        if not state["complaint_ready"]:
            state["questions_asked"] += 1
        if reply_text:
            await self._send_reply(req, thread_key, reply_text)

        await self._save_state(thread_key, state)

        return {
            "identityStatus": state["identity_status"],
            "questionsAsked": state["questions_asked"],
            "complaintReady": state["complaint_ready"],
            "extractedFields": state["extracted_fields"],
        }

    async def _tool_confirm_identity(self, req: TestEventRequest, state: dict, args: dict) -> dict:
        declared_anonymous = bool(args.get("declaredAnonymous", False))
        identity_type = args.get("identityType") or req.channelIdentity.type
        identity_value = args.get("identityValue") or req.channelIdentity.value
        # Only trust "verified" when the model is confirming the channel's own native
        # identity (unchanged value); a value the citizen typed in chat is not.
        verified = req.channelIdentity.verified and identity_value == req.channelIdentity.value

        resolve_req = ResolveRequest(
            tenantId=self._tenant_id,
            channel=req.channel,
            channelIdentity=ResolverChannelIdentityIn(
                type=identity_type, value=identity_value, verified=verified,
            ),
            threadId=req.threadId,
            declaredAnonymous=declared_anonymous,
            confirmedEmail=identity_value if (identity_type == "email" and not declared_anonymous) else None,
            confirmedPhone=identity_value if (identity_type == "phone" and not declared_anonymous) else None,
            confirmedName=args.get("name"),
            rawText=req.rawText,
            traceId=req.traceId,
        )
        resolver = IdentityResolver(self._db, self._publisher)
        result = await resolver.resolve(resolve_req)

        state["identity_status"] = result.get("identityStatus", state["identity_status"])
        state["master_id"] = result.get("masterId", state.get("master_id"))
        if req.ticketId:
            await update_ticket_identity(
                self._db, req.ticketId, state["master_id"], state["identity_status"], trace_id=req.traceId)
        return result

    async def _tool_submit_complaint(self, req: TestEventRequest, thread_key: str, state: dict, args: dict) -> dict:
        extracted = {
            "complaint_summary": (args.get("complaint_summary") or "").strip(),
            "category_hint": args.get("category_hint", "other"),
        }
        state["extracted_fields"] = extracted
        state["complaint_ready"] = True

        logger.info("complaint ready (assistant) traceId=%s threadId=%s identityStatus=%s category=%s",
                    req.traceId, thread_key, state["identity_status"], extracted["category_hint"])
        message_id = await self._publisher.publish(streams.COMPLAINT_READY, build_event(
            self._tenant_id, "complaint.ready", {
                "threadId": thread_key,
                "ticketId": req.ticketId,
                "identityStatus": state["identity_status"],
                "masterId": state.get("master_id"),
                "channel": req.channel,
                "channelIdentityValue": req.channelIdentity.value,
                "extractedFields": extracted,
            }, trace_id=req.traceId))
        return {"complaintReady": True, "messageId": message_id}

    @staticmethod
    def _render_user_message(req: TestEventRequest) -> str:
        lines = [
            f"channel: {req.channel}",
            f"channel_identity_type: {req.channelIdentity.type}",
            f"channel_identity_value: {req.channelIdentity.value}",
            f"channel_identity_verified: {req.channelIdentity.verified}",
            f"message: {req.rawText}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _render_additional_instructions(req: TestEventRequest, state: dict) -> str:
        remaining = max(settings.ai_max_followup_questions - state["questions_asked"], 0)
        parts = [
            f"identity_status={state['identity_status']}",
            f"questions_asked={state['questions_asked']}",
            f"max_followup_questions={settings.ai_max_followup_questions}",
        ]
        if remaining == 0 and not state["complaint_ready"]:
            parts.append("You have used all follow-up questions: call submit_complaint now.")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _thread_key(req: TestEventRequest) -> str:
        """Stable conversation key, used even when the channel omits threadId."""
        return req.threadId or f"{req.channel}:{req.channelIdentity.value or 'anon'}"

    async def _send_reply(
        self, req: TestEventRequest, thread_key: str, text: str, is_identity_request: bool = False,
    ) -> None:
        await self._publisher.publish(streams.AI_REPLY_SEND, build_event(
            self._tenant_id, "ai.reply.send", {
                "channel": req.channel,
                "threadId": thread_key,
                "channelIdentityValue": req.channelIdentity.value,
                "messageText": text,
                "isIdentityRequest": is_identity_request,
                "isAnonymousAck": req.declaredAnonymous,
                "ticketNumber": req.ticketNumber,
            }, trace_id=req.traceId))

    async def _load_state(self, thread_key: str) -> Optional[dict]:
        key = f"conv:{self._tenant_id}:{thread_key}"
        try:
            raw = await get_valkey().get(key)
        except Exception as exc:  # noqa: BLE001 - state read is best-effort
            logger.warning("failed to load conversation state: %s", exc)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def _save_state(self, thread_key: str, state: dict) -> None:
        key = f"conv:{self._tenant_id}:{thread_key}"
        ttl = settings.conversation_state_ttl_hours * 3600
        try:
            await get_valkey().set(key, json.dumps(state), ex=ttl)
        except Exception as exc:  # noqa: BLE001 - state persistence is best-effort
            logger.warning("failed to save conversation state: %s", exc)
