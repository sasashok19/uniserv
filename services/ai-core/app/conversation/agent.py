"""Conversation agent orchestration (Feature 06): identity gate + info gathering."""

import json
import logging
from typing import Optional

from pydantic import BaseModel

from app.classify.classifier import classify
from app.config import settings
from app.conversation.llm import LLMGateway
from app.events import streams
from app.events.client import get_valkey
from app.events.event import build_event
from app.events.publisher import BasePublisher

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
        self._llm = LLMGateway()

    async def process(self, req: TestEventRequest) -> dict:
        # --- Identity gate ---
        if not req.channelIdentity.verified and not req.declaredAnonymous:
            await self._send_reply(req, IDENTITY_REQUEST_MESSAGE, is_identity_request=True)
            await self._save_state(req, {"identity_status": "pending", "questions_asked": 0})
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
            await self._send_reply(req, FOLLOWUP_QUESTION)
            complaint_ready = False
        else:
            questions_asked = 0
            complaint_ready = True

        extracted = {"complaint_summary": summary, "category_hint": category_hint}

        if complaint_ready:
            await self._publisher.publish(streams.COMPLAINT_READY, build_event(
                self._tenant_id, "complaint.ready", {
                    "threadId": req.threadId,
                    "identityStatus": identity_status,
                    "extractedFields": extracted,
                }))

        await self._save_state(req, {
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

    async def _send_reply(self, req: TestEventRequest, text: str, is_identity_request: bool = False):
        await self._publisher.publish(streams.AI_REPLY_SEND, build_event(
            self._tenant_id, "ai.reply.send", {
                "channel": req.channel,
                "threadId": req.threadId,
                "channelIdentityValue": req.channelIdentity.value,
                "messageText": text,
                "isIdentityRequest": is_identity_request,
                "isAnonymousAck": req.declaredAnonymous,
            }))

    async def _save_state(self, req: TestEventRequest, state: dict):
        key = f"conv:{self._tenant_id}:{req.threadId}"
        ttl = settings.conversation_state_ttl_hours * 3600
        try:
            await get_valkey().set(key, json.dumps(state), ex=ttl)
        except Exception as exc:  # noqa: BLE001 - state persistence is best-effort
            logger.warning("failed to save conversation state: %s", exc)
