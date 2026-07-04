"""Conversation agent HTTP API (Feature 06)."""

from fastapi import APIRouter

from app.conversation.agent import ConversationAgent, TestEventRequest
from app.conversation.llm import LLMGateway

router = APIRouter()


@router.post("/api/v1/internal/process-test-event")
async def process_test_event(req: TestEventRequest) -> dict:
    agent = ConversationAgent(req.tenantId)
    return await agent.process(req)


@router.post("/api/v1/internal/test-llm-health")
async def test_llm_health() -> dict:
    available = LLMGateway().is_available()
    return {
        "llmAvailable": available,
        "fallback": None if available else "rule_based_classification",
    }
