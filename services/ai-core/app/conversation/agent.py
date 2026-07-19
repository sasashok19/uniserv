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
from app.conversation.intake_fields import (
    FIELD_CATALOG,
    build_identity_request_message,
    extract_configured_fields,
    fields_for_channel,
    is_native_field,
    missing_fields,
)
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

FOLLOWUP_QUESTION = (
    "Thanks for reaching out. Could you tell us a bit more about what went wrong "
    "so we can help — for example the service affected and what happened?"
)

# Rule-based fallback only (no LLM to interpret a free-text reply). Which
# fields are asked, and which are mandatory, is now configurable per tenant
# per channel (Feature 15/16 — see app/conversation/intake_fields.py) rather
# than a single hardcoded "only Name blocks the gate" rule. A self-typed
# value with no label isn't handled here (that needs real NLU — see the
# OpenAI assistant path's confirm_identity tool).
_ANONYMOUS_REPLY_RE = re.compile(r"\banonymous\b", re.IGNORECASE)


def _flatten_intake(intake: dict) -> dict:
    """`{key: {"value":..., "source":...}}` -> `{key: value}`, keeping only
    what the citizen actually wrote in THIS message — the shape every OTHER
    consumer (ticket message formatting, service_id persistence) expects.
    Native (channel address) and known (already-on-file) values are
    deliberately excluded: they'd otherwise pad every ticket's "citizen
    provided" summary with facts that were never actually written down in
    this particular message."""
    return {k: v["value"] for k, v in intake.items() if v.get("source") == "extracted"}


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
    # This message's own Message-ID (Feature 15, email only) — used as a
    # per-message-unique fallback thread key so a brand-new, unrelated email
    # from an address that already has an open ticket never gets folded into
    # it just because there's no real In-Reply-To to disambiguate (see
    # ConversationAgent._thread_key). Also persisted as the ticket's
    # origin_message_id for outbound reply threading.
    messageId: Optional[str] = None


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
        # Conversation memory is keyed by the STABLE ticket (see _conv_key),
        # not the per-message email thread_key — otherwise a citizen's reply
        # (which threads off our identity-request email) would land on a new
        # key and lose the saved complaint. thread_key is still used for
        # event routing / the reply's threadId.
        state_key = self._conv_key(req)
        # The intake form is a SEPARATE reply from the complaint description,
        # so once identity is confirmed we recall what the citizen originally
        # wrote (saved below) rather than classify the intake reply itself.
        state = await self._load_state(state_key) or {}

        # --- Identity gate (Feature 15/16: configurable per-channel fields) ---
        declared_anonymous = req.declaredAnonymous or bool(_ANONYMOUS_REPLY_RE.search(req.rawText or ""))
        tenant_config = await self._db.get_tenant_config(req.tenantId, trace_id=req.traceId)
        field_configs = fields_for_channel(tenant_config, req.channel)

        # A declared-anonymous citizen is never looked up (they've explicitly
        # opted out of being identified) — only fields flagged
        # mandatory-even-if-anonymous (e.g. a Service/Customer ID needed to
        # route the complaint) can still block the gate for them.
        known = None if declared_anonymous else await self._find_known_identity(req)
        intake = extract_configured_fields(
            req.rawText, req.channel, req.channelIdentity.value, req.channelIdentity.verified,
            field_configs, known=known,
        )
        missing = missing_fields(intake, field_configs, declared_anonymous)
        if missing:
            original_text = state.get("original_raw_text") or req.rawText
            is_first_ask = not state.get("original_raw_text")
            message = build_identity_request_message(
                field_configs, req.channel, req.channelIdentity.verified, missing, is_first_ask)
            logger.info("identity gate: requesting identity traceId=%s threadId=%s missing=%s",
                        req.traceId, thread_key, missing)
            await self._send_reply(req, thread_key, message, is_identity_request=True)
            await self._save_state(state_key, {
                "identity_status": "pending",
                "questions_asked": 0,
                "original_raw_text": original_text,
            })
            return {
                "identityStatus": "pending",
                "identityRequestSent": True,
                "complaintReady": False,
            }

        # Gate passed. If this thread was previously asked for identity, this
        # reply IS the intake form, not the complaint description — recall
        # what the citizen originally wrote instead of classifying the
        # intake reply itself. Otherwise (identity resolved immediately —
        # known citizen, native channel, or everything mandatory was already
        # in the first message) this message itself is the complaint.
        summary_source = state.get("original_raw_text") or req.rawText
        master_id = await self._resolve_master_id(req, declared_anonymous, intake=intake)
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
        flat_intake = _flatten_intake(intake)
        if flat_intake:
            extracted["intake"] = flat_intake

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

        await self._save_state(state_key, {
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
        """The existing identity profile for this citizen's channel address,
        if any (Feature 15/16) — used by `extract_configured_fields` to
        auto-satisfy already-on-file fields per-field, instead of the old
        all-or-nothing "has a name on file -> skip everything" check."""
        value = req.channelIdentity.value
        if not value:
            return None
        if req.channelIdentity.type == "email":
            return await self._db.find_by_email(req.tenantId, value, trace_id=req.traceId)
        if req.channelIdentity.type == "phone":
            return await self._db.find_by_phone(req.tenantId, value, trace_id=req.traceId)
        return None

    async def _resolve_master_id(
        self, req: TestEventRequest, declared_anonymous: bool, intake: Optional[dict] = None,
    ) -> Optional[str]:
        """Resolve (or create) the citizen's identity profile. Idempotent for
        confirmed phone/email (find-or-create by value), so calling this more
        than once per thread (e.g. once when the gate passes, again if a
        later turn re-derives it) is safe — the anonymous path's
        fresh-ref-per-call behaviour is an accepted Phase-1 simplification.

        Only "native" (the channel's own address) or "extracted" (freshly
        written in THIS message) intake values are trusted here — a "known"
        value is already on file and isn't a new signal, and feeding it back
        in would risk re-triggering resolution/merge logic based on stale
        data (see app/conversation/intake_fields.py).
        """
        def _trusted(key: str) -> Optional[str]:
            entry = (intake or {}).get(key)
            if not entry or entry.get("source") not in ("native", "extracted"):
                return None
            if entry.get("valid") is False:
                return None
            return entry.get("value")

        native_email = req.channelIdentity.value if req.channelIdentity.type == "email" else None
        confirmed_phone = _trusted("mobile")
        confirmed_email = (native_email if not declared_anonymous else None) or _trusted("email")
        confirmed_name = _trusted("name")
        resolve_req = ResolveRequest(
            tenantId=req.tenantId,
            channel=req.channel,
            channelIdentity=ResolverChannelIdentityIn(
                type=req.channelIdentity.type, value=req.channelIdentity.value, verified=req.channelIdentity.verified,
            ),
            threadId=req.threadId,
            declaredAnonymous=declared_anonymous,
            confirmedPhone=confirmed_phone,
            confirmedEmail=confirmed_email,
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
        # Memory + the OpenAI thread are keyed by the stable ticket, not the
        # per-message email thread_key (see _conv_key) — this is what keeps the
        # original complaint in context across the identity back-and-forth so
        # the assistant doesn't re-ask for details already given.
        state_key = self._conv_key(req)
        state = await self._load_state(state_key) or {
            "identity_status": "pending",
            "master_id": None,
            "extracted_fields": {},
            "questions_asked": 0,
            "complaint_ready": False,
        }
        # Remember the citizen's first substantive message as the complaint, so
        # that even if the OpenAI thread is reset (e.g. state TTL expired
        # mid-conversation) the complaint is still carried into the per-turn
        # instructions rather than being asked for again.
        if not state.get("original_complaint") and (req.rawText or "").strip():
            state["original_complaint"] = req.rawText.strip()

        tenant_config = await self._db.get_tenant_config(req.tenantId, trace_id=req.traceId)
        field_configs = fields_for_channel(tenant_config, req.channel)

        user_message = self._render_user_message(req)
        additional_instructions = self._render_additional_instructions(req, state, field_configs)

        async def execute_tool(name: str, args: dict) -> dict:
            if name == "confirm_identity":
                return await self._tool_confirm_identity(req, state, args)
            if name == "submit_complaint":
                return await self._tool_submit_complaint(req, thread_key, state, args)
            return {"error": f"unknown tool '{name}'"}

        reply_text = await self._openai.run_turn(
            self._tenant_id, state_key, user_message, execute_tool, additional_instructions,
        )

        if not state["complaint_ready"]:
            state["questions_asked"] += 1
        if reply_text:
            await self._send_reply(req, thread_key, reply_text)

        await self._save_state(state_key, state)

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
    def _render_additional_instructions(req: TestEventRequest, state: dict, field_configs: list[dict]) -> str:
        remaining = max(settings.ai_max_followup_questions - state["questions_asked"], 0)
        parts = [
            f"identity_status={state['identity_status']}",
            f"questions_asked={state['questions_asked']}",
            f"max_followup_questions={settings.ai_max_followup_questions}",
        ]
        if remaining == 0 and not state["complaint_ready"]:
            parts.append("You have used all follow-up questions: call submit_complaint now.")
        # Carry the citizen's original complaint forward so the assistant uses
        # it instead of asking the citizen to repeat what they already sent in
        # their first message (a common complaint when identity is collected
        # across several email turns).
        original = state.get("original_complaint")
        if original and not state["complaint_ready"]:
            snippet = original if len(original) <= 600 else original[:600]
            parts.append(
                "The citizen's original message was: " + json.dumps(snippet)
                + ". If it already describes their problem, treat THAT as the complaint_summary and "
                "call submit_complaint as soon as identity is resolved — do not ask them to repeat "
                "what they already told you."
            )
        # Feature 15/16: best-effort hint only — the Assistant's own tool
        # schema/instructions aren't regenerated per tenant, so this can't
        # enforce the configurable mandatory-field gate the way the
        # rule-based path does; it just tells the model what this tenant
        # currently requires for this channel before confirm_identity.
        mandatory = [
            FIELD_CATALOG[fc["key"]]["label"] for fc in field_configs
            if fc.get("mandatory") and not is_native_field(fc["key"], req.channel, req.channelIdentity.verified)
        ]
        if mandatory:
            parts.append(f"required_identity_fields_for_this_channel={', '.join(mandatory)}")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _thread_key(req: TestEventRequest) -> str:
        """Stable conversation key, used even when the channel omits threadId.

        WhatsApp has no subject/message-id concept and one persistent thread
        per phone number is correct there, so it keeps the address-based
        fallback. Email is different: a citizen sends many UNRELATED emails
        from the same address over time, and folding every one of them
        without a real In-Reply-To into a single "email:<address>" key would
        (and did) collapse a brand-new complaint into whatever ticket that
        address last had open. Falling back to this message's own
        Message-ID instead makes every email-without-a-reply-header its own
        thread by default — a genuine reply is still found via its
        In-Reply-To (req.threadId) or, more robustly, via the ticket-number
        embedded in the subject (see app/tickets/intake.py).
        """
        if req.threadId:
            return req.threadId
        if req.channel == "email" and req.messageId:
            return f"email:{req.messageId}"
        return f"{req.channel}:{req.channelIdentity.value or 'anon'}"

    @staticmethod
    def _conv_key(req: "TestEventRequest") -> str:
        """Key for conversation MEMORY (Valkey state) and the OpenAI thread.

        This must stay STABLE across a multi-turn email exchange. The email
        ``_thread_key`` changes with every inbound Message-ID / In-Reply-To
        (a citizen's reply threads off OUR identity-request email, not their
        original), so keying memory on it made each turn a fresh conversation
        with no recollection of the original complaint — the assistant then
        re-asked for details the citizen already gave. The TICKET is the
        stable anchor (matched by subject ticket-number in
        ``ensure_ticket_stub``), so prefer it. Falls back to the thread_key
        for direct/test calls that have no ticket yet."""
        if req.ticketId:
            return f"ticket:{req.ticketId}"
        return ConversationAgent._thread_key(req)

    async def _send_reply(
        self, req: TestEventRequest, thread_key: str, text: str, is_identity_request: bool = False,
    ) -> None:
        origin_message_id = None
        if req.ticketId:
            try:
                ticket = await self._db.get_ticket(req.ticketId, trace_id=req.traceId)
                origin_message_id = ticket.get("origin_message_id")
            except Exception:  # noqa: BLE001 - threading is best-effort, never blocks the reply itself
                logger.warning("failed to fetch origin_message_id for reply threading traceId=%s ticketId=%s",
                                req.traceId, req.ticketId)
        await self._publisher.publish(streams.AI_REPLY_SEND, build_event(
            self._tenant_id, "ai.reply.send", {
                "channel": req.channel,
                "threadId": thread_key,
                "channelIdentityValue": req.channelIdentity.value,
                "messageText": text,
                "isIdentityRequest": is_identity_request,
                "isAnonymousAck": req.declaredAnonymous,
                "ticketNumber": req.ticketNumber,
                "originMessageId": origin_message_id,
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
