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

logger = logging.getLogger("ai-core")

IDENTITY_REQUEST_MESSAGE = (
    "Thanks for reaching out. To help you better, could you share your email "
    "address or mobile number? If you'd prefer to stay anonymous, just reply "
    "'anonymous' and we'll still register your complaint."
)

FOLLOWUP_QUESTION = (
    "Thanks for reaching out. Could you tell us a bit more about what went wrong "
    "so we can help — for example the service affected and what happened?"
)


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


class ConversationAgent:
    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id
        self._publisher = BasePublisher(get_valkey(), tenant_id)
        self._db = DbWriterClient()
        self._openai = OpenAIAssistantGateway()

    async def process(self, req: TestEventRequest) -> dict:
        if self._openai.is_available():
            try:
                return await self._process_via_assistant(req)
            except Exception:  # noqa: BLE001 - graceful degradation to rule-based
                logger.exception("OpenAI assistant turn failed; falling back to rule-based pipeline")
        return await self._process_rule_based(req)

    # ------------------------------------------------------------------
    # Rule-based fallback (Phase 1 dev default — no LLM key configured)
    # ------------------------------------------------------------------

    async def _process_rule_based(self, req: TestEventRequest) -> dict:
        thread_key = self._thread_key(req)

        # --- Identity gate ---
        if not req.channelIdentity.verified and not req.declaredAnonymous:
            await self._send_reply(req, thread_key, IDENTITY_REQUEST_MESSAGE, is_identity_request=True)
            await self._save_state(thread_key, {"identity_status": "pending", "questions_asked": 0})
            return {
                "identityStatus": "pending",
                "identityRequestSent": True,
                "complaintReady": False,
            }

        identity_status = "anonymous" if req.declaredAnonymous else "confirmed"

        # --- Info gathering ---
        summary = (req.rawText or "").strip()
        classification = classify(summary)
        category_hint = classification["category"]
        vague = category_hint == "other" or len(summary.split()) < 4

        if vague and settings.ai_max_followup_questions >= 1:
            questions_asked = 1
            await self._send_reply(req, thread_key, FOLLOWUP_QUESTION)
            complaint_ready = False
        else:
            questions_asked = 0
            complaint_ready = True

        extracted = {"complaint_summary": summary, "category_hint": category_hint}

        if complaint_ready:
            await self._publisher.publish(streams.COMPLAINT_READY, build_event(
                self._tenant_id, "complaint.ready", {
                    "threadId": thread_key,
                    "identityStatus": identity_status,
                    "extractedFields": extracted,
                }))

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
                return await self._tool_submit_complaint(thread_key, state, args)
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
            rawText=req.rawText,
        )
        resolver = IdentityResolver(self._db, self._publisher)
        result = await resolver.resolve(resolve_req)

        state["identity_status"] = result.get("identityStatus", state["identity_status"])
        state["master_id"] = result.get("masterId", state.get("master_id"))
        return result

    async def _tool_submit_complaint(self, thread_key: str, state: dict, args: dict) -> dict:
        extracted = {
            "complaint_summary": (args.get("complaint_summary") or "").strip(),
            "category_hint": args.get("category_hint", "other"),
        }
        state["extracted_fields"] = extracted
        state["complaint_ready"] = True

        message_id = await self._publisher.publish(streams.COMPLAINT_READY, build_event(
            self._tenant_id, "complaint.ready", {
                "threadId": thread_key,
                "identityStatus": state["identity_status"],
                "masterId": state.get("master_id"),
                "extractedFields": extracted,
            }))
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
            }))

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
