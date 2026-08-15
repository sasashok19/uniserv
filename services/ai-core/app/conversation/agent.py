"""Conversation agent orchestration (Feature 06): identity gate + info gathering.

Two execution paths:
- ``_process_via_assistant``: the OpenAI **Responses API** (conversations +
  tool calls) when ``OPENAI_API_KEY`` is configured. Falls back to the
  rule-based path on any failure (graceful degradation). This ran on the
  Assistants API until Feature 27 — see ``openai_gateway`` for why it moved and
  what changed.
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
    build_identity_request_message,
    catalog_for_tenant,
    extract_configured_fields,
    fields_for_channel,
    is_native_field,
    missing_fields,
    suggest_email_correction,
    validate_email,
)
from app.conversation import menu_content
from app.conversation.openai_gateway import OpenAIAssistantGateway
from app.conversation.status_lookup import summarize_recent_tickets
from app.events import streams
from app.events.client import get_valkey
from app.events.event import build_event
from app.events.publisher import BasePublisher
from app.identity.db_client import DbWriterClient
from app.identity.resolver import ChannelIdentityIn as ResolverChannelIdentityIn
from app.identity.resolver import IdentityResolver, ResolveRequest
from app.tickets import chief_complaint
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

# Feature 17: a citizen asking about an EXISTING complaint ("what's the
# status of my last complaint?") is a fundamentally different turn from one
# describing a new problem or replying to an intake question — it should
# never be gated on identity/mandatory fields, and must never itself be
# treated as a complaint to file. Deliberately requires an explicit
# status/update/progress word NEAR a complaint/ticket/case word (rather than
# just "my complaint(s)" alone), so a genuine new complaint's own wording
# ("my complaint is that my meter isn't working") never false-positives —
# this is channel-agnostic by design (same check for email and WhatsApp).
_STATUS_INQUIRY_RE = re.compile(
    r"\b(status|update|progress|news)\b.{0,40}\b(complaint|ticket|issue|case)s?\b"
    r"|\b(complaint|ticket|issue|case)s?\b.{0,40}\b(status|update|progress)\b"
    r"|\bhow(?:'s|’s| is| are)\b.{0,20}\b(complaint|ticket|issue|case)s?\b.{0,20}\b(going|doing|progressing)\b"
    r"|\bwhat(?:'s|’s| is)?\b.{0,20}\bhappen(?:ed|ing)?\b.{0,30}\b(complaint|ticket|issue|case)\b",
    re.IGNORECASE,
)


def _effective_max_followups(tenant_config: dict) -> int:
    """Follow-up-question budget for this tenant (Feature 04 general settings).

    Uses ``generalSettings.maxFollowupQuestions`` when it's a valid int in
    [0, 5]; otherwise falls back to the ``AI_MAX_FOLLOWUP_QUESTIONS`` env
    default. `bool` is rejected explicitly (it's an `int` subclass in Python,
    and a stray `true`/`false` in config should not be read as 1/0)."""
    value = (tenant_config or {}).get("generalSettings", {}).get("maxFollowupQuestions")
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 5:
        return value
    return settings.ai_max_followup_questions


def _flatten_intake(intake: dict) -> dict:
    """`{key: {"value":..., "source":...}}` -> `{key: value}`, keeping only
    what the citizen actually wrote in THIS message — the shape every OTHER
    consumer (ticket message formatting, service_id persistence) expects.
    Native (channel address) and known (already-on-file) values are
    deliberately excluded: they'd otherwise pad every ticket's "citizen
    provided" summary with facts that were never actually written down in
    this particular message."""
    return {k: v["value"] for k, v in intake.items() if v.get("source") == "extracted"}


# Intake keys that map onto a column of the TICKET itself rather than onto the
# citizen's identity profile. Name/email/mobile are identity attributes and
# reach the database through the resolver; the Service/Customer ID is
# complaint-specific and has nowhere else to go (Feature 20).
_TICKET_COLUMN_FOR_INTAKE_KEY = {"serviceId": "serviceId"}


def _ticket_fields_from_intake(intake: dict) -> dict:
    """Ticket columns derivable from what the citizen has supplied so far.

    Written on every confirm_identity turn, not only once the whole gate
    passes, so a partially-completed intake is still visible on the ticket
    (Feature 20). Only values the citizen actually wrote and that passed their
    field's validator are included — a "known" value is already on file, and
    an invalid one is about to be queried, not recorded."""
    fields = {}
    for key, column in _TICKET_COLUMN_FOR_INTAKE_KEY.items():
        entry = (intake or {}).get(key) or {}
        if entry.get("value") and entry.get("valid", True) and entry.get("source") == "extracted":
            fields[column] = entry["value"]
    return fields


def _merge_provided_fields(state: dict, provided_fields: dict, catalog: dict) -> None:
    """Merge the assistant's explicit `confirm_identity(providedFields=...)`
    argument (label -> value) into the tracked intake state (Feature 17).

    This is the bridge a label-anchored regex can't be: the model has
    already understood the citizen's own words ("it's Ashok" is obviously a
    name to a human, but matches no "name ..." pattern), so once it hands
    that understanding back to us explicitly, it's authoritative — no
    validation-of-plausibility beyond the catalog's own validator, and it
    overwrites rather than defers to whatever (if anything) the per-turn
    regex pass already found, since this is a deliberate, later signal.
    Unknown labels (a typo, or a label from a stale/different tenant
    config) are silently ignored rather than raising — a chat turn must
    never crash because the model echoed back a slightly wrong label.
    """
    if not provided_fields:
        return
    label_to_key = {spec["label"]: key for key, spec in catalog.items()}
    intake = state.setdefault("intake", {})
    for label, value in provided_fields.items():
        key = label_to_key.get(label)
        if not key or not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        intake[key] = {"value": value, "valid": catalog[key]["validate"](value), "source": "extracted"}


# Feature 20: "ask to confirm OR correct" has to mean both, and the two have
# to mean the RIGHT things. The question the citizen is asked is *'you sent
# "x@gmaill.com"; did you mean "x@gmail.com"?'* — so "yes" means **take the
# suggestion**, not "keep what I typed". (Reading it the other way round is
# the single most likely reply re-introducing the exact typo this feature
# exists to catch.) Standing by the original therefore requires the citizen to
# send it again, which the wording explicitly invites; that path matters
# because the domain list is a heuristic and a real, unusual address must
# never be re-asked forever.
#
# Deliberately narrow, and only consulted on a SHORT message: an answer to a
# yes/no question is short, whereas words like "right" or "same" turn up
# constantly in ordinary complaint prose ("the transformer on the right side",
# "same problem again") and must not be read as answers to a question asked
# several turns ago.
_AFFIRMATION_RE = re.compile(
    r"\b(yes|yeah|yep|yup|ok(ay)?|correct|confirm(ed|ing)?"
    r"|that'?s (right|correct|it)|thats (right|correct|it))\b",
    re.IGNORECASE)
_MAX_AFFIRMATION_WORDS = 6


def _resolve_queried_values(state: dict, raw_text: Optional[str]) -> None:
    """Settle any value the citizen was asked to confirm or correct, using
    their own words this turn (see the note above). Mutates `state["intake"]`.

    - They sent the same value again -> accept it as-is (they overrule us).
    - They said yes and we offered a correction -> apply the correction.
    - They said yes and we offered none -> accept the value as-is.
    Anything else leaves it outstanding, and the question is asked again.

    Each decision is REMEMBERED (``{"asked": ..., "resolved": ...}``) and
    re-applied, because the model resends every value it knows on every
    ``confirm_identity`` call: without that, the citizen's own correction is
    settled at the top of the turn and then quietly undone a few lines later
    when the model's resent copy of the original is merged back in.
    """
    queried = state.get("queried_intake") or {}
    if not queried:
        return
    intake = state.get("intake") or {}
    text = raw_text or ""
    affirmed = bool(_AFFIRMATION_RE.search(text)) and len(text.split()) <= _MAX_AFFIRMATION_WORDS
    for key, record in list(queried.items()):
        asked, resolved = record.get("asked"), record.get("resolved")
        entry = intake.get(key) or {}
        if resolved:
            if entry.get("value") == asked:
                entry["value"], entry["valid"] = resolved, True
            continue
        if entry.get("value") != asked or entry.get("valid", True):
            # They've moved on to a different value for this field (or it was
            # accepted some other way) — the question no longer applies.
            queried.pop(key, None)
            continue
        if asked.lower() in text.lower():
            entry["valid"], record["resolved"] = True, asked
            logger.info("intake value accepted: citizen sent it again unchanged field=%s", key)
        elif affirmed:
            suggestion = suggest_email_correction(asked) if key == "email" else None
            entry["value"] = record["resolved"] = suggestion or asked
            entry["valid"] = True
            logger.info("intake value settled on citizen's confirmation field=%s corrected=%s",
                        key, bool(suggestion))


def _remember_queried_values(state: dict, missing: list[str]) -> None:
    """Record which supplied-but-refused values the citizen is about to be
    asked about, so the next turn can interpret their answer."""
    if not missing:
        return
    queried = state.setdefault("queried_intake", {})
    for key, entry in (state.get("intake") or {}).items():
        if not entry.get("value") or entry.get("valid", True):
            continue
        # A record for a DIFFERENT value is stale — the citizen has since sent
        # something else for this field, and that is what they're now being
        # asked about. Replacing it (rather than keeping the first one forever)
        # is what lets a second attempt be confirmed or corrected in its turn.
        if (queried.get(key) or {}).get("asked") != entry["value"]:
            queried[key] = {"asked": entry["value"]}


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
    # Feature 19: the id of the message THIS one replies to -- a WhatsApp
    # swipe-reply's context.id (Meta's quoted-message reference) or an
    # email's In-Reply-To header. When it matches some OTHER ticket's own
    # origin_message_id, that's the most explicit "this continues that
    # ticket" signal a citizen can give -- see app/tickets/intake.py
    # ensure_ticket_stub, which checks it before any text/identity heuristic.
    inReplyTo: Optional[str] = None
    # Feature 22: set by ensure_ticket_stub when this message MIGHT continue an
    # existing open complaint but the text doesn't settle it (e.g. "water
    # logging" when the open one says "water logging in Madambakkam"). Shape:
    # {"id", "ticketNumber", "summary"}. Nothing is merged on this alone — the
    # assistant asks the citizen, and `resolve_duplicate` acts on their answer.
    suspectedDuplicateOf: Optional[dict] = None


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
        if _STATUS_INQUIRY_RE.search(req.rawText or ""):
            return await self._handle_status_inquiry(req, thread_key)
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
        catalog = catalog_for_tenant(tenant_config)
        field_configs = fields_for_channel(tenant_config, req.channel, catalog=catalog)
        max_followups = _effective_max_followups(tenant_config)

        # A declared-anonymous citizen is never looked up (they've explicitly
        # opted out of being identified) — only fields flagged
        # mandatory-even-if-anonymous (e.g. a Service/Customer ID needed to
        # route the complaint) can still block the gate for them.
        known = None if declared_anonymous else await self._find_known_identity(req)
        intake = extract_configured_fields(
            req.rawText, req.channel, req.channelIdentity.value, req.channelIdentity.verified,
            field_configs, known=known, catalog=catalog,
        )
        missing = missing_fields(intake, field_configs, declared_anonymous, catalog=catalog)
        if missing:
            original_text = state.get("original_raw_text") or req.rawText
            is_first_ask = not state.get("original_raw_text")
            message = build_identity_request_message(
                field_configs, req.channel, req.channelIdentity.verified, missing, is_first_ask,
                catalog=catalog)
            logger.info("identity gate: requesting identity traceId=%s threadId=%s missing=%s",
                        req.traceId, thread_key, missing)
            await self._persist_inbound(req, req.rawText)
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
            await update_ticket_identity(self._db, req.ticketId, master_id, identity_status, trace_id=req.traceId,
                                         extra_fields=_ticket_fields_from_intake(intake))

        # --- Info gathering ---
        summary = (summary_source or "").strip()
        classification = classify(summary)
        category_hint = classification["category"]
        vague = category_hint == "other" or len(summary.split()) < 4

        if vague and max_followups >= 1:
            questions_asked = 1
            logger.info("info gathering: vague complaint, asking follow-up traceId=%s threadId=%s",
                        req.traceId, thread_key)
            # Not complaint-ready this turn, so create_ticket_from_complaint
            # (which would otherwise persist this text) never runs — persist
            # it here instead, or the citizen's message is lost from
            # Conversation entirely (this is the common case for a
            # follow-up reply on an already-open ticket, e.g. one asking for
            # more detail or just answering the follow-up question above).
            await self._persist_inbound(req, req.rawText)
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

    async def _handle_status_inquiry(self, req: TestEventRequest, thread_key: str) -> dict:
        """Feature 17: "what's the status of my complaint?" — a read-only
        query, never gated on identity/mandatory fields and never itself
        treated as a complaint to file. Shared by the rule-based path (this
        method) and the assistant path's `check_complaint_status` tool
        (`_tool_check_status`), so both channels get the identical summary
        logic — only how the INTENT is detected differs (regex here, the
        model's own judgement there), matching how the rest of this class
        already treats the two paths' mechanisms as appropriately different
        while sharing the underlying data/behaviour.
        """
        summary = await summarize_recent_tickets(
            self._db, req.tenantId, req.channelIdentity.type, req.channelIdentity.value, trace_id=req.traceId)
        logger.info("status inquiry handled traceId=%s threadId=%s", req.traceId, thread_key)
        await self._persist_inbound(req, req.rawText)
        await self._send_reply(req, thread_key, summary)
        return {"identityStatus": "n/a", "complaintReady": False, "statusInquiry": True}

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

    async def _update_intake_and_get_missing(
        self, req: TestEventRequest, state: dict, field_configs: list[dict], catalog: dict,
    ) -> list[str]:
        """Merge this turn's message into the tenant's configured mandatory
        intake fields and return what's still missing (Feature 15/16 — the
        assistant-path equivalent of the rule-based path's gate at the top of
        ``_process_rule_based``).

        The Assistant's own tool schema has no way to express a tenant's
        configured mandatory fields (``confirm_identity`` only carries
        identity type/value; ``submit_complaint`` only carries the complaint
        summary/category) — previously this gate existed ONLY as a per-turn
        instruction *hint* to the model (see ``_render_additional_instructions``),
        and that hint itself disappeared the instant a verified channel (e.g.
        WhatsApp) auto-confirmed identity, before the model had ever asked for
        Name/Email. That let a bare "Meter not working" WhatsApp message reach
        a fully-confirmed ticket with none of the tenant's mandatory fields.

        This runs the SAME extractor/validator the rule-based path uses,
        merging across turns (a field satisfied on an earlier turn is never
        re-asked), so the result here is enforced in code by
        ``_tool_confirm_identity``/``_tool_submit_complaint`` — independent of
        whatever tool the model chooses to call.
        """
        if _ANONYMOUS_REPLY_RE.search(req.rawText or ""):
            state["declared_anonymous"] = True
        declared_anonymous = bool(state.get("declared_anonymous", False))

        known = None if declared_anonymous else await self._find_known_identity(req)
        extracted = extract_configured_fields(
            req.rawText, req.channel, req.channelIdentity.value, req.channelIdentity.verified,
            field_configs, known=known, catalog=catalog,
        )
        intake = state.setdefault("intake", {})
        for key, entry in extracted.items():
            existing = intake.get(key)
            has_existing_value = bool(existing) and existing.get("value") is not None
            if has_existing_value and existing.get("valid", True):
                continue                      # satisfied on an earlier turn — never re-ask
            if entry.get("value") is None and has_existing_value:
                # Nothing new for this field this turn. Keeping what the
                # citizen already sent matters even though it was refused
                # (Feature 20): overwriting it with an empty extraction loses
                # the very value the correction question is about, so the next
                # ask degrades to a bare "we still need: Email" and their
                # answer has nothing left to attach to.
                continue
            intake[key] = entry
        # Applied here too (not only in `_tool_confirm_identity`) so the
        # per-turn instructions and the tool result agree about what is still
        # outstanding on the turn a citizen stands by a queried value.
        _resolve_queried_values(state, req.rawText)
        return missing_fields(intake, field_configs, declared_anonymous, catalog=catalog)

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
        catalog = catalog_for_tenant(tenant_config)
        field_configs = fields_for_channel(tenant_config, req.channel, catalog=catalog)
        max_followups = _effective_max_followups(tenant_config)
        missing = await self._update_intake_and_get_missing(req, state, field_configs, catalog)

        user_message = self._render_user_message(req)
        additional_instructions = self._render_additional_instructions(
            req, state, field_configs, max_followups, catalog, missing,
            company=menu_content.resolve(tenant_config).get("companyName"))

        submitted_this_turn = False

        async def execute_tool(name: str, args: dict) -> dict:
            nonlocal submitted_this_turn, missing
            if name == "confirm_identity":
                result = await self._tool_confirm_identity(req, state, args, field_configs, catalog)
                # declaredAnonymous may have just been set true by this call,
                # which changes which fields are mandatory (mandatoryIfAnonymous)
                # — refresh so a submit_complaint call later in this SAME turn
                # is gated against the citizen's actual anonymity choice.
                missing = result.get("missingFields", missing)
                return result
            if name == "submit_complaint":
                if missing:
                    logger.info(
                        "submit_complaint refused: mandatory intake fields still missing "
                        "traceId=%s threadId=%s missing=%s",
                        req.traceId, thread_key, missing,
                    )
                    return {
                        "error": "intake_incomplete",
                        "missingFields": missing,
                        "message": (
                            "This tenant still requires: " + ", ".join(missing)
                            + ". Ask the citizen for these before calling submit_complaint again."
                        ),
                    }
                # Feature 18: the model's own honesty check on its
                # complaint_summary — refused in code (not just discouraged
                # by the instructions above) so an unclear/likely-mistyped
                # complaint can't slip through just because the model
                # decided to submit anyway. Channel-agnostic here: email's
                # HARD reject (no ticket at all) happens earlier, before a
                # stub ever exists (dispatcher.py's coherence pre-check) —
                # by the time submit_complaint runs, a stub already exists
                # for every channel, so the only remaining option is to ask
                # for confirmation, not to un-create anything.
                if not args.get("is_coherent", True):
                    logger.info(
                        "submit_complaint refused: complaint text judged unclear/incoherent "
                        "traceId=%s threadId=%s",
                        req.traceId, thread_key,
                    )
                    return {
                        "error": "unclear_complaint",
                        "message": (
                            "The complaint text seems unclear or possibly mistyped. Ask the "
                            "citizen to confirm or clarify what they meant before calling "
                            "submit_complaint again."
                        ),
                    }
                submitted_this_turn = True
                return await self._tool_submit_complaint(req, thread_key, state, args)
            if name == "check_complaint_status":
                return await self._tool_check_status(req)
            if name == "resolve_duplicate":
                return await self._tool_resolve_duplicate(req, args)
            return {"error": f"unknown tool '{name}'"}

        reply_text = await self._openai.run_turn(
            self._tenant_id, state_key, user_message, execute_tool, additional_instructions,
        )

        if not submitted_this_turn:
            # submit_complaint (which create_ticket_from_complaint persists
            # from) wasn't called this turn — a plain identity exchange or
            # conversational reply, including a follow-up on an
            # already-resolved ticket, otherwise never lands in Conversation.
            await self._persist_inbound(req, req.rawText)

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

    async def _tool_confirm_identity(
        self, req: TestEventRequest, state: dict, args: dict,
        field_configs: list[dict], catalog: dict,
    ) -> dict:
        declared_anonymous = bool(args.get("declaredAnonymous", False))
        if declared_anonymous:
            state["declared_anonymous"] = True
        # Feature 17 fix: providedFields is the bridge between what the model
        # already correctly understood from casual conversation (e.g. "it's
        # Ashok") and the missing_fields gate below, which previously only
        # ever saw whatever a label-anchored regex could re-derive from raw
        # text — and silently kept a ticket "pending" forever whenever a
        # citizen answered without literally saying the field's name.
        _merge_provided_fields(state, args.get("providedFields") or {}, catalog)
        identity_type = args.get("identityType") or req.channelIdentity.type
        identity_value = args.get("identityValue") or req.channelIdentity.value
        # An email the model reports as the IDENTITY value is the same citizen
        # statement as one it reports via providedFields — the tool schema just
        # offers two ways to say it — so it is merged into the tracked intake
        # the same way (Feature 20). Without this, an address supplied as
        # identityValue was validated but never recorded, so a refused one
        # produced only a bare "we still need: Email" and the citizen was never
        # told what was wrong with the address they had just sent.
        if identity_type == "email" and identity_value and "email" in catalog:
            _merge_provided_fields(state, {catalog["email"]["label"]: identity_value}, catalog)
        _resolve_queried_values(state, req.rawText)
        # Only trust "verified" when the model is confirming the channel's own native
        # identity (unchanged value); a value the citizen typed in chat is not.
        verified = req.channelIdentity.verified and identity_value == req.channelIdentity.value

        confirmed_email = identity_value if (identity_type == "email" and not declared_anonymous) else None
        confirmed_phone = identity_value if (identity_type == "phone" and not declared_anonymous) else None
        # Feature 20: an address the intake validator refused (bad syntax, or a
        # one-keystroke miss like "gmaill.com") must not be written onto the
        # citizen's identity profile — the gate below is already going to ask
        # them to confirm or correct it, and a profile silently carrying the
        # typo would send every future notification into a black hole. The
        # value is not discarded, just not yet trusted: it stays in the intake
        # state so `missing_fields` can quote it back in the correction ask.
        intake_email = (state.get("intake", {}) or {}).get("email") or {}
        email_accepted = validate_email(confirmed_email) or (
            # ...or the citizen has already settled this exact address (stood
            # by it after being asked), which overrules the validator.
            intake_email.get("value") == confirmed_email and bool(intake_email.get("valid"))
        )
        if confirmed_email and not email_accepted:
            logger.info(
                "confirm_identity: not accepting an unvalidated email onto the identity profile "
                "traceId=%s ticketId=%s suggestion=%s",
                req.traceId, req.ticketId, suggest_email_correction(confirmed_email),
            )
            confirmed_email = None
        if confirmed_email is None and not declared_anonymous:
            # The model can also hand the email over as a providedFields entry
            # rather than as identityType/identityValue (it does exactly that
            # when confirming a verified WhatsApp number as the identity while
            # relaying the citizen's email as one more requested field) — take
            # it from the merged intake state, which has already validated it.
            if (intake_email.get("value") and intake_email.get("valid")
                    and intake_email.get("source") in ("native", "extracted")):
                confirmed_email = intake_email["value"]
        # Sourced from the SAME merged intake state the gate checks below —
        # not a separate "name" tool argument (the schema never declared
        # one, so it was always None) — guaranteeing the identity profile
        # and the gate agree on what "name" was actually provided.
        confirmed_name = (state.get("intake", {}).get("name") or {}).get("value")
        # The channel's own NATIVE identity always rides along, whatever the model
        # confirmed with. Without this, an email citizen who confirms via a typed
        # phone number gets a phone-only profile — their sender address (known all
        # along) is silently dropped, the dashboard's Email column stays blank, and
        # a later email from them can't find the profile. Mirrors the rule-based
        # path, where the native identity is always fed to the resolver.
        if not declared_anonymous:
            if confirmed_email is None and req.channelIdentity.type == "email":
                confirmed_email = req.channelIdentity.value
            if confirmed_phone is None and req.channelIdentity.type == "phone" and req.channelIdentity.verified:
                confirmed_phone = req.channelIdentity.value

        resolve_req = ResolveRequest(
            tenantId=self._tenant_id,
            channel=req.channel,
            # The REAL channel identity — the model's confirmed value travels via
            # confirmedEmail/confirmedPhone above, so overriding the channel
            # identity with it would only corrupt channel_ids_json (e.g. an
            # "email" channel entry holding a phone number).
            channelIdentity=ResolverChannelIdentityIn(
                type=req.channelIdentity.type, value=req.channelIdentity.value, verified=verified,
            ),
            threadId=req.threadId,
            declaredAnonymous=declared_anonymous,
            confirmedEmail=confirmed_email,
            confirmedPhone=confirmed_phone,
            confirmedName=confirmed_name,
            rawText=req.rawText,
            traceId=req.traceId,
        )
        resolver = IdentityResolver(self._db, self._publisher)
        result = await resolver.resolve(resolve_req)

        missing = missing_fields(
            state.get("intake", {}), field_configs, bool(state.get("declared_anonymous", False)), catalog=catalog,
        )
        _remember_queried_values(state, missing)
        resolved_status = result.get("identityStatus", state["identity_status"])
        # Feature 15/16: a verified channel (e.g. WhatsApp) resolves identity
        # trivially, but that's a different question from "is this ticket
        # ready to leave the intake gate" — don't surface identity_status as
        # confirmed/anonymous (which is what moves a ticket into the
        # dashboard's Confirmed queue, see TicketsResource/dashboard scope
        # filter) until the tenant's mandatory intake fields are ALSO
        # satisfied, mirroring the rule-based path's ordering (gate before
        # resolve).
        state["identity_status"] = "pending" if missing else resolved_status
        state["master_id"] = result.get("masterId", state.get("master_id"))
        if req.ticketId:
            await update_ticket_identity(
                self._db, req.ticketId, state["master_id"], state["identity_status"], trace_id=req.traceId,
                extra_fields=_ticket_fields_from_intake(state.get("intake", {})))
        return {**result, "identityStatus": state["identity_status"], "missingFields": missing}

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

    async def _tool_resolve_duplicate(self, req: TestEventRequest, args: dict) -> dict:
        """Feature 22: the citizen has answered "is this the same complaint?".

        Only the citizen can settle it, so this runs on their answer and
        nothing else — routing merely raised the suspicion. On a "yes" the
        ticket created for this message is folded into the original, using the
        same treatment a detected duplicate has always had
        (`isDuplicate`/`parentTicketId`/closed, see app/tickets/service.py) so
        there is one code path for "this is a duplicate", not two. On a "no"
        the suspicion is simply dropped and the new ticket stands alone.
        """
        suspected = req.suspectedDuplicateOf or {}
        parent_id, parent_number = suspected.get("id"), suspected.get("ticketNumber")
        if not parent_id or not req.ticketId:
            return {"error": "no_suspected_duplicate",
                    "message": "There is no pending duplicate question on this conversation."}
        if not args.get("isDuplicate"):
            logger.info("citizen says this is NOT a duplicate traceId=%s ticketId=%s of=%s",
                        req.traceId, req.ticketId, parent_number)
            # Clears the flag an agent would otherwise still see on this ticket.
            try:
                await self._db.add_event(req.ticketId, {
                    "eventType": "ticket.duplicate_dismissed",
                    "actorType": "ai",
                    "meta": {"duplicateOfId": parent_id, "duplicateOfNumber": parent_number},
                }, trace_id=req.traceId)
            except Exception:  # noqa: BLE001 - best-effort audit
                logger.warning("failed to record duplicate-dismissed event traceId=%s", req.traceId)
            return {"isDuplicate": False, "message": "Understood — treated as a separate complaint."}
        if parent_id == req.ticketId:
            return {"error": "same_ticket", "message": "That is this ticket."}

        await self._db.add_message(parent_id, {
            "tenantId": req.tenantId,
            "channel": req.channel,
            "direction": "inbound",
            "authorType": "user",
            "content": req.rawText,
        }, trace_id=req.traceId)
        # The citizen has just confirmed this text belongs to the ORIGINAL
        # complaint, so it refines that ticket's chief complaint — the merge
        # moves the message across, and this moves what it tells us with it.
        await chief_complaint.refresh(self._db, parent_id, req.rawText, trace_id=req.traceId)
        await self._db.update_ticket(req.ticketId, {
            "isDuplicate": 1,
            "parentTicketId": parent_id,
            "status": "closed",
        }, trace_id=req.traceId)
        # Audit trail on the ORIGINAL: without this, the ticket silently grows
        # an extra message and an agent has no record of where it came from or
        # that the citizen confirmed it.
        try:
            await self._db.add_event(parent_id, {
                "eventType": "ticket.duplicate_merged",
                "actorType": "ai",
                "meta": {"mergedFromId": req.ticketId, "mergedFromNumber": req.ticketNumber},
            }, trace_id=req.traceId)
            # ...and on the ticket that WAS the duplicate, so its own trail says
            # where it went rather than just showing an unexplained close.
            await self._db.add_event(req.ticketId, {
                "eventType": "ticket.duplicate_confirmed",
                "actorType": "ai",
                "meta": {"duplicateOfId": parent_id, "duplicateOfNumber": parent_number},
            }, trace_id=req.traceId)
        except Exception:  # noqa: BLE001 - the merge itself is done; the audit line is best-effort
            logger.warning("failed to record duplicate-merge audit event traceId=%s parentId=%s",
                            req.traceId, parent_id)
        logger.info("citizen confirmed duplicate traceId=%s ticketId=%s mergedInto=%s",
                    req.traceId, req.ticketId, parent_number)
        return {"isDuplicate": True, "mergedInto": parent_number,
                "message": f"Merged into {parent_number}. Tell the citizen their message was added to "
                           f"their existing complaint {parent_number}, and do not call submit_complaint."}

    async def _tool_check_status(self, req: TestEventRequest) -> dict:
        """Feature 17: the assistant-path equivalent of `_handle_status_inquiry`
        (rule-based path) — same underlying `summarize_recent_tickets` call, so
        both paths give the citizen the identical summary regardless of
        channel. The composed text is returned to the model as `summary`
        rather than sent directly, so it flows through the SAME single
        end-of-turn `_send_reply` call every other tool result does (avoiding
        a double-send); `ASSISTANT_INSTRUCTIONS` tells the model to relay it
        verbatim rather than paraphrase.
        """
        summary = await summarize_recent_tickets(
            self._db, req.tenantId, req.channelIdentity.type, req.channelIdentity.value, trace_id=req.traceId)
        return {"summary": summary}

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
    def _render_additional_instructions(
        req: TestEventRequest, state: dict, field_configs: list[dict], max_followups: int,
        catalog: Optional[dict] = None, missing: Optional[list[str]] = None,
        company: Optional[str] = None,
    ) -> str:
        # max_followups is the tenant-effective budget (Feature 04) threaded in
        # by the caller — generalSettings.maxFollowupQuestions when valid, else
        # the AI_MAX_FOLLOWUP_QUESTIONS env default.
        remaining = max(max_followups - state["questions_asked"], 0)
        parts = [
            f"identity_status={state['identity_status']}",
            f"questions_asked={state['questions_asked']}",
            f"max_followup_questions={max_followups}",
        ]
        # Feature 26: the tenant's own name. The Assistant object is shared by
        # every tenant and lives on OpenAI's side, so its baked-in instructions
        # cannot name one — this per-turn line is the only place a tenant name
        # can reach the model at all.
        if company:
            parts.append(f"company={company}")
        # Feature 22: routing suspected this continues an existing complaint but
        # couldn't tell. Surfaced with the other complaint's own words so the
        # model can ask a specific question ("...the water logging in
        # Madambakkam?") rather than a generic "is this a duplicate?", which a
        # citizen has no way to answer usefully.
        suspected = req.suspectedDuplicateOf or {}
        if suspected.get("ticketNumber") and not state.get("complaint_ready"):
            parts.append(
                "POSSIBLE DUPLICATE: this citizen already has an open complaint "
                + str(suspected["ticketNumber"]) + " which reads: "
                + json.dumps(suspected.get("summary", ""))
                + ". This message may or may not be about that same issue. Ask them ONE short "
                "question naming that complaint's specific detail (its location or subject) to "
                "find out, then call resolve_duplicate with their answer. Do not call "
                "submit_complaint until that is settled."
            )
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
        # Feature 15/16: the Assistant's own tool schema/instructions aren't
        # regenerated per tenant, so per-turn instructions are how the tenant's
        # configured intake fields reach it. Be DIRECTIVE, not a passive hint —
        # the base instructions ("ask for an email or phone number") otherwise
        # win and the model ignores the tenant's field list entirely.
        #
        # `missing` (computed server-side by _update_intake_and_get_missing,
        # merged across turns) is what's actually enforced by
        # _tool_confirm_identity/_tool_submit_complaint — this is no longer
        # just a hint the model can ignore. Gating on `missing` directly
        # (rather than identity_status != "confirmed") matters because a
        # verified channel (WhatsApp) confirms identity trivially, before any
        # tenant-mandatory Name/Email has ever been collected.
        if not state.get("complaint_ready") and missing:
            spec_by_key = catalog if catalog is not None else catalog_for_tenant(None)
            optional = [
                spec_by_key[fc["key"]]["label"] for fc in field_configs
                if not fc.get("mandatory") and not is_native_field(fc["key"], req.channel, req.channelIdentity.verified)
            ]
            if req.channel == "email" and req.channelIdentity.value:
                parts.append(
                    f"The citizen's email address is already known from the channel ({req.channelIdentity.value}) — "
                    "NEVER ask for their email; treat it as provided."
                )
            parts.append(
                "This tenant still REQUIRES these details before the complaint can be confirmed: "
                + ", ".join(missing)
                + ". Ask for ALL of them (that the citizen hasn't already given) in ONE message"
                + (", optionally also offering: " + ", ".join(optional) if optional else "")
                + ". Still call confirm_identity immediately as instructed above, but calling "
                "submit_complaint before these are provided will be REJECTED by the system — it will "
                "not create the ticket, so keep asking instead."
            )
            parts.append(
                "When you call confirm_identity, pass the citizen's name in the `name` argument if they "
                'have stated it anywhere in this conversation (e.g. "My name is ...").'
            )
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

    async def _persist_inbound(self, req: TestEventRequest, content: Optional[str]) -> None:
        """Record the citizen's raw message on the ticket's Conversation
        timeline. Only the turn that actually publishes complaint.ready
        skips this — create_ticket_from_complaint (services/ai-core/app/tickets/service.py)
        persists that one instead, using its richer intake-augmented content
        — every other turn (identity exchange, follow-up question, or a
        conversational reply on an already-resolved ticket) would otherwise
        never appear anywhere. Best-effort: a persistence failure must not
        block the conversation turn or the reply the citizen is waiting on.
        """
        if not req.ticketId or not (content or "").strip():
            return
        try:
            await self._db.add_message(req.ticketId, {
                "tenantId": req.tenantId,
                "channel": req.channel,
                "direction": "inbound",
                "authorType": "user",
                "content": content,
            }, trace_id=req.traceId)
        except Exception:  # noqa: BLE001 - Conversation logging is best-effort
            logger.warning("failed to persist inbound message traceId=%s ticketId=%s",
                            req.traceId, req.ticketId)
        # Feature 23: every citizen message the dashboard shows also updates
        # the ticket's chief complaint. Placed here, at the one point every
        # inbound turn passes through, rather than at each of the callers —
        # the FIRST message that triggered the ticket lands here too (a stub
        # is created before this runs), which is what gives a ticket a chief
        # complaint before its complaint has even been filed. It is its own
        # best-effort call, deliberately outside the try above, so a failure
        # to persist the message does not skip the update or vice versa.
        await chief_complaint.refresh(self._db, req.ticketId, content, trace_id=req.traceId)

    async def _persist_outbound_ai_reply(
        self, req: TestEventRequest, text: str, is_identity_request: bool = False,
    ) -> Optional[str]:
        """Record the AI's own reply on the ticket's Conversation timeline —
        previously this was only ever emailed out (see app/notifications/sender.py)
        and never written anywhere the dashboard could show it. Best-effort,
        same reasoning as `_persist_inbound`.

        Returns the message row's id so the send path can stamp the provider's
        own id onto it once delivery succeeds (Feature 24), or None if nothing
        was persisted. `is_identity_request` is recorded because routing has to
        know whether the last thing we asked on a stub was an intake question:
        a bare "yes" may only be read as an intake answer where one was asked.
        """
        if not req.ticketId or not (text or "").strip():
            return None
        try:
            recorded = await self._db.add_message(req.ticketId, {
                "tenantId": req.tenantId,
                "channel": req.channel,
                "direction": "outbound",
                "authorType": "ai",
                "content": text,
                "isAiGenerated": 1,
                "isIntakeRequest": 1 if is_identity_request else 0,
            }, trace_id=req.traceId)
            return (recorded or {}).get("id")
        except Exception:  # noqa: BLE001 - Conversation logging is best-effort
            logger.warning("failed to persist outbound AI reply traceId=%s ticketId=%s",
                            req.traceId, req.ticketId)
            return None

    async def _send_reply(
        self, req: TestEventRequest, thread_key: str, text: str, is_identity_request: bool = False,
    ) -> None:
        message_id = await self._persist_outbound_ai_reply(req, text, is_identity_request)
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
                # Feature 24: which message row this send corresponds to, so the
                # consumer can stamp the provider's id onto it after delivery.
                # Carried through the event because persistence happens here and
                # delivery happens in the ai.reply.send consumer.
                "ticketId": req.ticketId,
                "messageId": message_id,
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
