"""Unit tests for the conversation agent (Feature 06).

Covers the rule-based fallback (no LLM configured) and the OpenAI Assistants
path (mocked client — no live API calls), including the confirm_identity and
submit_complaint tool handlers.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.conversation.agent import ChannelIdentityIn, ConversationAgent, TestEventRequest
from app.conversation.openai_gateway import OpenAIAssistantGateway


def _run(coro):
    return asyncio.run(coro)


def _req(**overrides) -> TestEventRequest:
    defaults = dict(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="unknown@test.com", verified=False),
        rawText="I have a complaint about my bill",
        threadId="thread-001",
    )
    defaults.update(overrides)
    return TestEventRequest(**defaults)


# ---------------------------------------------------------------------------
# Rule-based fallback (no OPENAI_ASSISTANT_ID configured)
# ---------------------------------------------------------------------------

def test_rule_based_identity_gate_triggers_for_unverified_email():
    agent = ConversationAgent("t1")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_save_state", new=AsyncMock()) as save_state:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(_req()))

    assert result == {"identityStatus": "pending", "identityRequestSent": True, "complaintReady": False}
    save_state.assert_awaited_once()


def test_rule_based_whatsapp_verified_clear_complaint_is_ready():
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My electricity bill for March is double the usual amount",
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["identityStatus"] == "confirmed"
    assert result["complaintReady"] is True
    assert result["extractedFields"]["category_hint"] == "billing"
    publisher.publish.assert_awaited_once()
    stream_arg = publisher.publish.await_args.args[0]
    assert stream_arg == "complaint.ready"


def test_rule_based_vague_complaint_asks_one_followup():
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Something is wrong",
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    assert result["questionsAsked"] == 1
    stream_arg = publisher.publish.await_args.args[0]
    assert stream_arg == "ai.reply.send"


# ---------------------------------------------------------------------------
# OpenAI Assistants path (mocked gateway / tool handlers)
# ---------------------------------------------------------------------------

def test_openai_gateway_unavailable_without_assistant_id():
    with patch("app.conversation.openai_gateway.settings") as settings:
        settings.openai_api_key = "sk-test"
        settings.openai_assistant_id = ""
        assert OpenAIAssistantGateway().is_available() is False


def test_openai_gateway_available_with_key_and_assistant():
    with patch("app.conversation.openai_gateway.settings") as settings:
        settings.openai_api_key = "sk-test"
        settings.openai_assistant_id = "asst_123"
        assert OpenAIAssistantGateway().is_available() is True


def test_openai_gateway_run_turn_drives_tool_call_loop_to_completion():
    """Exercises the requires_action -> submit_tool_outputs -> completed state machine."""
    gateway = OpenAIAssistantGateway()

    fake_thread = SimpleNamespace(id="thread_abc")
    tool_call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="submit_complaint", arguments="{}"))
    run_requires_action = SimpleNamespace(
        status="requires_action",
        id="run_1",
        required_action=SimpleNamespace(submit_tool_outputs=SimpleNamespace(tool_calls=[tool_call])),
    )
    run_completed = SimpleNamespace(status="completed", id="run_1")
    final_message = SimpleNamespace(data=[SimpleNamespace(
        content=[SimpleNamespace(type="text", text=SimpleNamespace(value="Thanks, logged your complaint."))]
    )])

    fake_client = SimpleNamespace(
        beta=SimpleNamespace(threads=SimpleNamespace(
            create=AsyncMock(return_value=fake_thread),
            messages=SimpleNamespace(create=AsyncMock(), list=AsyncMock(return_value=final_message)),
            runs=SimpleNamespace(
                create_and_poll=AsyncMock(return_value=run_requires_action),
                submit_tool_outputs_and_poll=AsyncMock(return_value=run_completed),
            ),
        ))
    )

    valkey = AsyncMock()
    valkey.get.return_value = None

    execute_tool = AsyncMock(return_value={"complaintReady": True})

    with patch.object(OpenAIAssistantGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        settings.openai_assistant_id = "asst_123"
        settings.conversation_state_ttl_hours = 2
        reply = _run(gateway.run_turn("t1", "thread-key", "hello", execute_tool))

    assert reply == "Thanks, logged your complaint."
    execute_tool.assert_awaited_once_with("submit_complaint", {})
    fake_client.beta.threads.runs.submit_tool_outputs_and_poll.assert_awaited_once()
    _, kwargs = fake_client.beta.threads.runs.submit_tool_outputs_and_poll.await_args
    assert kwargs["tool_outputs"] == [{"tool_call_id": "call_1", "output": json.dumps({"complaintReady": True})}]


def test_tool_confirm_identity_calls_resolver_and_updates_state():
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
    )
    state = {"identity_status": "pending", "master_id": None}

    resolved = {"masterId": "m-1", "identityStatus": "confirmed", "isNew": True}
    with patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(return_value=resolved)
        result = _run(agent._tool_confirm_identity(req, state, {"declaredAnonymous": False}))

    assert result == resolved
    assert state["identity_status"] == "confirmed"
    assert state["master_id"] == "m-1"


def test_tool_submit_complaint_publishes_complaint_ready():
    agent = ConversationAgent("t1")
    state = {"identity_status": "confirmed", "master_id": "m-1"}
    with patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="9-0")
        result = _run(agent._tool_submit_complaint(
            "thread-key", state, {"complaint_summary": "bill is wrong", "category_hint": "billing"}))

    assert result == {"complaintReady": True, "messageId": "9-0"}
    assert state["complaint_ready"] is True
    assert state["extracted_fields"] == {"complaint_summary": "bill is wrong", "category_hint": "billing"}
    publisher.publish.assert_awaited_once()
    stream_arg, event_arg = publisher.publish.await_args.args
    assert stream_arg == "complaint.ready"
    assert event_arg["payload"]["threadId"] == "thread-key"
    assert event_arg["payload"]["masterId"] == "m-1"
