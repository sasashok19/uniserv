"""Unit tests for the conversation agent (Feature 06 x 15/16).

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
#
# Every test below mocks `get_tenant_config` — an unmocked real
# `DbWriterClient` call would hit the network. Returning `{}` means "use the
# built-in default field config" (see app/conversation/intake_fields.py).
# ---------------------------------------------------------------------------

def test_identity_request_message_does_not_promote_anonymous():
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS, build_identity_request_message
    message = build_identity_request_message(
        DEFAULT_INTAKE_FIELDS["email"], "email", False, [], is_first_ask=True)
    assert "anonymous" not in message.lower()


def test_rule_based_identity_gate_triggers_for_unverified_email():
    agent = ConversationAgent("t1")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()) as save_state:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(_req()))

    assert result == {"identityStatus": "pending", "identityRequestSent": True, "complaintReady": False}
    save_state.assert_awaited_once()
    # First time asking: the full template, not a "still need" list.
    event_arg = publisher.publish.await_args.args[1]
    assert "Name" in event_arg["payload"]["messageText"]


def test_rule_based_name_alone_is_sufficient_no_mobile_needed():
    """Email channel already has the native from-address as a contact
    method, so Name is the only field that actually blocks the gate."""
    agent = ConversationAgent("t1")
    req = _req(rawText="Name: Jane Doe")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-4", "identityStatus": "confirmed"})
        result = _run(agent.process(req))

    assert result["identityStatus"] == "confirmed"
    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedName == "Jane Doe"
    assert resolve_req.confirmedPhone is None
    assert resolve_req.confirmedEmail == "unknown@test.com"


def test_rule_based_known_identity_skips_intake_entirely():
    """A returning citizen (same email, name+phone already on file) isn't
    asked for identity details again."""
    agent = ConversationAgent("t1")
    req = _req(rawText="My meter is faulty again this week")
    known = {"master_id": "m-7", "name": "Jane Doe", "phone": "9876543210"}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._db, "find_by_email", new=AsyncMock(return_value=known)):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["identityStatus"] == "confirmed"
    assert result["complaintReady"] is True
    stream_arg, event_arg = publisher.publish.await_args.args
    assert stream_arg == "complaint.ready"
    assert event_arg["payload"]["masterId"] == "m-7"


def test_rule_based_invalid_mobile_and_pincode_are_flagged_but_name_present_is_not():
    agent = ConversationAgent("t1")
    prior_state = {"identity_status": "pending", "questions_asked": 0, "original_raw_text": "My meter is faulty"}
    req = _req(rawText="Service ID: SC123, Mobile: 98765, Name: Jane, Pin code: 6002")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=prior_state)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    message = publisher.publish.await_args.args[1]["payload"]["messageText"]
    assert "Mobile Number (10 digits)" in message
    assert "Area Pin Code (6 digits)" in message
    assert "still need" in message
    assert "- Name" not in message  # name was supplied — not re-asked


def test_rule_based_second_ask_lists_only_what_is_still_missing():
    agent = ConversationAgent("t1")
    prior_state = {"identity_status": "pending", "questions_asked": 0, "original_raw_text": "My meter is faulty"}
    req = _req(rawText="My mobile is 9876543210 and pin code is 600028")  # no name yet
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=prior_state)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    message = publisher.publish.await_args.args[1]["payload"]["messageText"]
    assert "still need" in message
    assert "Name" in message
    assert "Mobile" not in message  # already supplied and valid


def test_rule_based_full_intake_reply_unblocks_gate_and_recalls_original_complaint():
    agent = ConversationAgent("t1")
    # Turn 1: original complaint, unverified email -> pending, original text saved.
    req1 = _req(rawText="My meter is faulty and showing wrong readings for the past week")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()) as save_state:
        publisher.publish = AsyncMock(return_value="1-0")
        _run(agent.process(req1))
    saved_state = save_state.await_args.args[1]
    assert saved_state["original_raw_text"] == req1.rawText

    # Turn 2: the intake form reply, no mention of the original complaint.
    req2 = _req(rawText="Service/Customer ID: SC98765\nMobile Number: 9876543210\nName: Jane Doe\nArea Pin Code: 600028")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=saved_state)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="2-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-9", "identityStatus": "confirmed"})
        result = _run(agent.process(req2))

    assert result["identityStatus"] == "confirmed"
    assert result["complaintReady"] is True
    # The complaint text is the ORIGINAL message, not the intake reply.
    assert result["extractedFields"]["complaint_summary"] == req1.rawText
    assert result["extractedFields"]["intake"]["serviceId"] == "SC98765"
    assert result["extractedFields"]["intake"]["mobile"] == "9876543210"
    assert result["extractedFields"]["intake"]["name"] == "Jane Doe"
    assert result["extractedFields"]["intake"]["pinCode"] == "600028"
    event_arg = publisher.publish.await_args.args[1]
    assert event_arg["payload"]["masterId"] == "m-9"
    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedPhone == "9876543210"
    assert resolve_req.confirmedName == "Jane Doe"


def test_rule_based_email_reply_anonymous_with_service_id_unblocks_identity_gate():
    """Anonymous still resolves without name/mobile/email — but the default
    config makes Service/Customer ID mandatory-even-if-anonymous, so it must
    be supplied to route the complaint."""
    agent = ConversationAgent("t1")
    req = _req(rawText="anonymous - I don't want to share details, my meter is faulty. Service ID: SC555")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "anon-1", "identityStatus": "anonymous"})
        result = _run(agent.process(req))

    assert result["identityStatus"] == "anonymous"
    assert result["complaintReady"] is True


def test_rule_based_email_reply_anonymous_without_service_id_still_asks():
    """Regression guard for the mandatory-even-if-anonymous flag: declaring
    anonymous does not bypass a field explicitly flagged to survive it."""
    agent = ConversationAgent("t1")
    req = _req(rawText="anonymous - I don't want to share details, my meter is faulty")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result == {"identityStatus": "pending", "identityRequestSent": True, "complaintReady": False}
    message = publisher.publish.await_args.args[1]["payload"]["messageText"]
    assert "Service" in message


def test_rule_based_whatsapp_known_citizen_clear_complaint_is_ready():
    """A returning WhatsApp citizen with name+email already on file gets no
    identity friction — matches the pre-existing "known" skip-ask UX."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My electricity bill for March is double the usual amount",
    )
    known = {"master_id": "m-1", "name": "Ravi Kumar", "email": "ravi@example.com", "phone": "+919876543210"}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=known)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent.process(req))

    assert result["identityStatus"] == "confirmed"
    assert result["complaintReady"] is True
    assert result["extractedFields"]["category_hint"] == "billing"
    stream_arg, event_arg = publisher.publish.await_args.args
    assert stream_arg == "complaint.ready"
    assert event_arg["payload"]["masterId"] == "m-1"


def test_rule_based_whatsapp_new_citizen_is_asked_for_email():
    """The actual fix: a brand-new (unknown) verified WhatsApp number no
    longer resolves silently — the default config requires email too, so
    the same person complaining by WhatsApp and by email later resolves to
    one identity instead of two."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My electricity bill for March is double the usual amount",
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()) as save_state:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result == {"identityStatus": "pending", "identityRequestSent": True, "complaintReady": False}
    message = publisher.publish.await_args.args[1]["payload"]["messageText"]
    assert "Name" in message
    assert "Email" in message
    assert "Mobile" not in message  # native to WhatsApp -- never asked
    save_state.assert_awaited_once()


def test_rule_based_vague_complaint_asks_one_followup():
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Something is wrong",
    )
    known = {"master_id": "m-5", "name": "Ravi Kumar", "email": "ravi@example.com", "phone": "+919876543210"}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=known)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-5", "identityStatus": "confirmed"})
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    assert result["questionsAsked"] == 1
    stream_arg = publisher.publish.await_args.args[0]
    assert stream_arg == "ai.reply.send"


def test_rule_based_whatsapp_email_provided_feeds_resolver_as_confirmed_email():
    """When a WhatsApp citizen supplies their email in the intake reply, it
    must reach the resolver as confirmedEmail (Feature 15/16) so cross-
    channel enrichment/merge can actually happen — this was the gap where a
    freshly-provided email was silently dropped."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Name: Ravi Kumar\nEmail: ravi@example.com\nMy electricity bill is wrong",
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-6", "identityStatus": "confirmed"})
        _run(agent.process(req))

    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedEmail == "ravi@example.com"
    assert resolve_req.confirmedName == "Ravi Kumar"


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
    req = _req()
    state = {"identity_status": "confirmed", "master_id": "m-1"}
    with patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="9-0")
        result = _run(agent._tool_submit_complaint(
            req, "thread-key", state, {"complaint_summary": "bill is wrong", "category_hint": "billing"}))

    assert result == {"complaintReady": True, "messageId": "9-0"}
    assert state["complaint_ready"] is True
    assert state["extracted_fields"] == {"complaint_summary": "bill is wrong", "category_hint": "billing"}
    publisher.publish.assert_awaited_once()
    stream_arg, event_arg = publisher.publish.await_args.args
    assert stream_arg == "complaint.ready"
    assert event_arg["payload"]["threadId"] == "thread-key"
    assert event_arg["payload"]["masterId"] == "m-1"
