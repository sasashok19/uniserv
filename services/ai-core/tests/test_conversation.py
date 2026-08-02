"""Unit tests for the conversation agent (Feature 06 x 15/16).

Covers the rule-based fallback (no LLM configured) and the OpenAI Assistants
path (mocked client — no live API calls), including the confirm_identity and
submit_complaint tool handlers.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.conversation.agent import (
    FOLLOWUP_QUESTION,
    ChannelIdentityIn,
    ConversationAgent,
    TestEventRequest,
    _effective_max_followups,
)
from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS, catalog_for_tenant
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
# Feature 04: tenant-configurable max follow-up questions
# ---------------------------------------------------------------------------

def test_effective_max_followups_uses_valid_tenant_override():
    assert _effective_max_followups({"generalSettings": {"maxFollowupQuestions": 0}}) == 0
    assert _effective_max_followups({"generalSettings": {"maxFollowupQuestions": 5}}) == 5


def test_effective_max_followups_falls_back_to_env_default_when_invalid_or_absent():
    from app.config import settings
    # Absent, out of range, wrong type, and bool (an int subclass) all fall back.
    assert _effective_max_followups({}) == settings.ai_max_followup_questions
    assert _effective_max_followups({"generalSettings": {"maxFollowupQuestions": 9}}) == settings.ai_max_followup_questions
    assert _effective_max_followups({"generalSettings": {"maxFollowupQuestions": "3"}}) == settings.ai_max_followup_questions
    assert _effective_max_followups({"generalSettings": {"maxFollowupQuestions": True}}) == settings.ai_max_followup_questions


def test_rule_based_tenant_override_zero_suppresses_followup_for_vague_complaint():
    """With maxFollowupQuestions=0 a vague complaint is filed immediately
    instead of asking a follow-up (contrast the default-2 behaviour in
    test_rule_based_vague_complaint_asks_one_followup)."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Something is wrong",
    )
    known = {"master_id": "m-5", "name": "Ravi Kumar", "email": "ravi@example.com", "phone": "+919876543210"}
    tenant_config = {"generalSettings": {"maxFollowupQuestions": 0}}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=known)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value=tenant_config)), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-5", "identityStatus": "confirmed"})
        result = _run(agent.process(req))

    assert result["questionsAsked"] == 0
    assert result["complaintReady"] is True
    # complaint.ready published straight away — no follow-up question sent.
    stream_arg = publisher.publish.await_args.args[0]
    assert stream_arg == "complaint.ready"


def test_render_additional_instructions_uses_threaded_max_followups():
    """The staticmethod reports and enforces the effective budget passed in,
    not the env default."""
    req = _req()
    state = {"identity_status": "confirmed", "questions_asked": 1, "complaint_ready": False}
    instr = ConversationAgent._render_additional_instructions(req, state, [], 1)
    assert "max_followup_questions=1" in instr
    # questions_asked (1) == budget (1) -> no remaining -> must submit now.
    assert "call submit_complaint now" in instr


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
    """No mandatory fields configured (empty field_configs) — identity_status
    passes straight through from the resolver, same as before Feature 15/16's
    assistant-path intake gate existed."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
    )
    state = {"identity_status": "pending", "master_id": None}

    resolved = {"masterId": "m-1", "identityStatus": "confirmed", "isNew": True}
    with patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(return_value=resolved)
        result = _run(agent._tool_confirm_identity(req, state, {"declaredAnonymous": False}, [], catalog_for_tenant(None)))

    assert result == {**resolved, "identityStatus": "confirmed", "missingFields": []}
    assert state["identity_status"] == "confirmed"
    assert state["master_id"] == "m-1"


def test_tool_submit_complaint_publishes_complaint_ready():
    """`_tool_submit_complaint` itself is unconditional by design — the
    Feature 15/16 mandatory-intake-fields gate lives one level up, in
    `_process_via_assistant`'s `execute_tool` closure (see the
    "assistant path: mandatory intake fields gate" tests below), so that
    submit_complaint's own tool-output shape stays simple regardless of
    channel/tenant config. This test covers the unconditional path only."""
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


# ---------------------------------------------------------------------------
# Assistant path: confirm_identity must not drop the channel's native identity
# ---------------------------------------------------------------------------


def test_tool_confirm_identity_carries_native_email_when_model_confirms_by_phone():
    """TKT-00001 regression: an email citizen who replies with a phone number
    must not end up with a phone-only profile — the sender address (and the
    real channel identity) ride along so the profile gets both."""
    agent = ConversationAgent("t1")
    req = _req(channelIdentity=ChannelIdentityIn(type="email", value="nithin@example.com", verified=False))
    state = {"identity_status": "pending", "master_id": None}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-9", "identityStatus": "confirmed"})
        _run(agent._tool_confirm_identity(
            req, state, {"identityType": "phone", "identityValue": "+917890678908"}, [], catalog_for_tenant(None)))

    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedPhone == "+917890678908"
    assert resolve_req.confirmedEmail == "nithin@example.com"
    # The REAL channel identity is preserved (not overwritten with the phone).
    assert resolve_req.channelIdentity.type == "email"
    assert resolve_req.channelIdentity.value == "nithin@example.com"


def test_tool_confirm_identity_anonymous_does_not_leak_native_email():
    agent = ConversationAgent("t1")
    req = _req(channelIdentity=ChannelIdentityIn(type="email", value="nithin@example.com", verified=False))
    state = {"identity_status": "pending", "master_id": None}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-a", "identityStatus": "anonymous"})
        _run(agent._tool_confirm_identity(req, state, {"declaredAnonymous": True}, [], catalog_for_tenant(None)))

    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.declaredAnonymous is True
    assert resolve_req.confirmedEmail is None
    assert resolve_req.confirmedPhone is None


# ---------------------------------------------------------------------------
# Assistant path: mandatory intake fields gate (Feature 15/16 bug fix).
#
# Reported bug: a verified WhatsApp sender's very first message ("Meter not
# working" — no name/email at all) reached a fully "Confirmed" ticket even
# though the tenant's intake-fields config marks Name and Email mandatory
# for the whatsapp channel. Root cause: the assistant path's only
# enforcement of mandatory fields was a per-turn instruction *hint* to the
# model, gated on `identity_status != "confirmed"` — and WhatsApp's verified
# phone number confirms identity trivially, before the model had ever asked
# for anything. `_update_intake_and_get_missing` + the `execute_tool` gates
# in `_process_via_assistant` are what closes that gap: mandatory fields are
# now enforced in code, independent of what the model decides to call.
# ---------------------------------------------------------------------------

def test_update_intake_and_get_missing_flags_everything_missing_on_bare_message():
    """The exact reported scenario: a brand-new verified WhatsApp number
    sends a message with no name/email indicators at all."""
    agent = ConversationAgent("t1")
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Meter not working",
    )
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    state = {}
    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)):
        missing = _run(agent._update_intake_and_get_missing(
            req, state, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert "Name" in missing
    assert "Email" in missing


def test_update_intake_and_get_missing_merges_across_turns():
    """A field satisfied on an earlier turn must not be re-asked, even
    though it's absent from the CURRENT turn's raw text — mirrors how the
    rule-based path never re-asks a field already given."""
    agent = ConversationAgent("t1")
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    field_configs = DEFAULT_INTAKE_FIELDS["whatsapp"]
    state = {}

    req1 = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Meter not working",
    )
    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)):
        missing1 = _run(agent._update_intake_and_get_missing(req1, state, field_configs, catalog_for_tenant(None)))
    assert set(missing1) == {"Name", "Email"}

    req2 = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My name is Ravi Kumar",
    )
    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)):
        missing2 = _run(agent._update_intake_and_get_missing(req2, state, field_configs, catalog_for_tenant(None)))
    assert missing2 == ["Email"]  # Name satisfied on turn 1, not re-asked


def test_update_intake_and_get_missing_known_identity_skips_reasking():
    """A returning WhatsApp citizen with name+email already on file gets no
    intake friction — same UX the rule-based path already guarantees."""
    agent = ConversationAgent("t1")
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My electricity bill for March is double the usual amount",
    )
    known = {"master_id": "m-1", "name": "Ravi Kumar", "email": "ravi@example.com", "phone": "+919876543210"}
    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=known)):
        missing = _run(agent._update_intake_and_get_missing(
            req, {}, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert missing == []


def test_update_intake_and_get_missing_anonymous_drops_name_email_but_keeps_service_id():
    """Declaring anonymous (detected from raw text, same heuristic as the
    rule-based path) drops ordinary-mandatory fields but not a field
    explicitly flagged mandatory-even-if-anonymous."""
    agent = ConversationAgent("t1")
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="anonymous - my meter is faulty",
    )
    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)):
        missing = _run(agent._update_intake_and_get_missing(
            req, {}, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert missing == ["Service/Customer ID"]


def test_tool_confirm_identity_holds_ticket_pending_when_mandatory_fields_missing():
    """The core fix: even though the resolver confirms a verified WhatsApp
    identity instantly, the TICKET must not be surfaced as identity-confirmed
    (which is what moves it into the dashboard's Confirmed queue) while
    Name/Email are still outstanding."""
    agent = ConversationAgent("t1")
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    req = _req(
        ticketId="tkt-whatsapp-1",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Meter not working",
    )
    state = {"identity_status": "pending", "master_id": None, "intake": {}}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-whatsapp-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state, {"declaredAnonymous": False}, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["identity_status"] == "pending"  # NOT "confirmed" — mandatory fields still missing
    assert result["identityStatus"] == "pending"
    assert set(result["missingFields"]) == {"Name", "Email"}
    update_ticket.assert_awaited_once()
    assert update_ticket.await_args.args[1]["identityStatus"] == "pending"


def test_tool_confirm_identity_promotes_to_confirmed_once_mandatory_fields_present():
    """Positive case: once Name/Email are both in the accumulated intake,
    confirm_identity DOES surface the real resolved status."""
    agent = ConversationAgent("t1")
    from app.conversation.intake_fields import DEFAULT_INTAKE_FIELDS
    req = _req(
        ticketId="tkt-whatsapp-2",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="My name is Ravi Kumar, email ravi@example.com",
    )
    state = {"identity_status": "pending", "master_id": None, "intake": {
        "name": {"value": "Ravi Kumar", "valid": True, "source": "extracted"},
        "email": {"value": "ravi@example.com", "valid": True, "source": "extracted"},
    }}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-whatsapp-2", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state, {"declaredAnonymous": False}, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["identity_status"] == "confirmed"
    assert result["identityStatus"] == "confirmed"
    assert result["missingFields"] == []
    assert update_ticket.await_args.args[1]["identityStatus"] == "confirmed"


def test_assistant_path_whatsapp_bare_message_does_not_reach_confirmed_or_complaint_ready():
    """End-to-end regression test for the reported bug, exercising the real
    `_process_via_assistant` turn (not just the tool handlers in isolation):
    a brand-new verified WhatsApp sender's first message is "Meter not
    working" with no name/email. The model calls confirm_identity (as its
    base instructions tell it to for a verified channel) and then attempts
    submit_complaint — both must be honoured/refused such that the ticket
    never reaches the Confirmed queue and no complaint.ready is published."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-whatsapp-3",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Meter not working",
    )

    submit_result_holder = {}

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        await execute_tool("confirm_identity", {"declaredAnonymous": False})
        submit_result_holder["result"] = await execute_tool(
            "submit_complaint", {"complaint_summary": "Meter not working", "category_hint": "technical"})
        return "Could you share your name and email so we can register your complaint?"

    with patch.object(OpenAIAssistantGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()) as save_state, \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher, \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-whatsapp-3", "identityStatus": "confirmed"})
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    # submit_complaint was refused — no complaint.ready published.
    assert submit_result_holder["result"]["error"] == "intake_incomplete"
    assert set(submit_result_holder["result"]["missingFields"]) == {"Name", "Email"}
    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" not in published_streams

    # The ticket stays "pending" — never surfaced as Confirmed — despite the
    # resolver having confirmed the (native, verified) WhatsApp identity.
    assert result["identityStatus"] == "pending"
    saved_state = save_state.await_args.args[1]
    assert saved_state["identity_status"] == "pending"
    assert result["complaintReady"] is False


def test_assistant_path_whatsapp_with_name_and_email_reaches_confirmed_and_complaint_ready():
    """Positive counterpart: once the citizen provides Name+Email (in a
    labeled, extractable form), the SAME flow succeeds end-to-end."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-whatsapp-4",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Name: Ravi Kumar\nEmail: ravi@example.com\nMeter not working",
    )

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        await execute_tool("confirm_identity", {"declaredAnonymous": False})
        await execute_tool(
            "submit_complaint", {"complaint_summary": "Meter not working", "category_hint": "technical"})
        return "Thanks, we've logged your complaint."

    with patch.object(OpenAIAssistantGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher, \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-whatsapp-4", "identityStatus": "confirmed"})
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["identityStatus"] == "confirmed"
    assert result["complaintReady"] is True
    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" in published_streams


def test_render_additional_instructions_lists_actually_missing_fields():
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
    )
    state = {"identity_status": "confirmed", "questions_asked": 0, "complaint_ready": False}
    instr = ConversationAgent._render_additional_instructions(
        req, state, DEFAULT_INTAKE_FIELDS["whatsapp"], 2, catalog_for_tenant(None), missing=["Name", "Email"])

    assert "Name" in instr
    assert "Email" in instr
    assert "REJECTED" in instr


def test_render_additional_instructions_omits_mandatory_hint_when_nothing_missing():
    """Even with identity_status='confirmed' (the OLD, buggy gating
    condition), an EMPTY missing list must suppress the block — `missing` is
    now the sole authority, not identity_status."""
    req = _req()
    state = {"identity_status": "confirmed", "questions_asked": 0, "complaint_ready": False}
    instr = ConversationAgent._render_additional_instructions(req, state, [], 2, {}, missing=[])
    assert "REQUIRES" not in instr
    assert "REJECTED" not in instr


# ---------------------------------------------------------------------------
# Feature 17: "what's the status of my complaint?" — status summary, shared
# by the rule-based path (regex intent detection) and the assistant path
# (check_complaint_status tool), both channel-agnostic.
# ---------------------------------------------------------------------------

def test_rule_based_status_inquiry_bypasses_identity_gate_and_never_files_a_complaint():
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-status-1", rawText="What's the status of my complaint?",
        channelIdentity=ChannelIdentityIn(type="email", value="citizen@example.com", verified=False),
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent._db, "find_by_email", new=AsyncMock(return_value={"master_id": "m-1"})), \
         patch.object(agent._db, "list_tickets", new=AsyncMock(return_value=[
             {"id": "t-1", "ticket_number": "TKT-00042", "category": "billing", "status": "resolved"},
         ])), \
         patch.object(agent._db, "get_notes", new=AsyncMock(return_value=[{"content": "Refund processed"}])), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result == {"identityStatus": "n/a", "complaintReady": False, "statusInquiry": True}
    publisher.publish.assert_awaited_once()  # ai.reply.send only — never complaint.ready
    stream_arg, event_arg = publisher.publish.await_args.args
    assert stream_arg == "ai.reply.send"
    assert "TKT-00042" in event_arg["payload"]["messageText"]
    assert "Refund processed" in event_arg["payload"]["messageText"]
    # the citizen's own inquiry is still recorded on the ticket's Conversation timeline
    inbound = next(c for c in add_message.await_args_list if c.args[1]["direction"] == "inbound")
    assert inbound.args[1]["content"] == "What's the status of my complaint?"


def test_rule_based_status_inquiry_works_for_whatsapp_identically():
    """Channel-agnostic by design: identical detection/handling for WhatsApp."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-status-2",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Any update on my last complaint?",
    )
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent._db, "find_by_phone", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["statusInquiry"] is True
    event_arg = publisher.publish.await_args.args[1]
    assert "don't have any complaints on file" in event_arg["payload"]["messageText"]


def test_rule_based_genuine_new_complaint_is_not_mistaken_for_status_inquiry():
    """Regression guard: ordinary complaint wording must never false-positive
    into the status-inquiry branch (no 'status'/'update'/'progress' words
    near 'complaint'/'ticket', so the identity gate runs as normal)."""
    agent = ConversationAgent("t1")
    req = _req(rawText="My meter is not working and it's been broken for days")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()):
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert "statusInquiry" not in result
    assert result["identityRequestSent"] is True  # normal identity gate ran


def test_status_inquiry_regex_matches_common_phrasings():
    from app.conversation.agent import _STATUS_INQUIRY_RE
    positives = [
        "What's the status of my complaint?",
        "any update on my last complaint",
        "How's my ticket going?",
        "what happened to my complaint",
        "Can you give me a progress update on my issue",
    ]
    for text in positives:
        assert _STATUS_INQUIRY_RE.search(text), f"expected a match for: {text!r}"

    negatives = [
        "My meter is not working",
        "My electricity bill for March is double the usual amount",
        "My complaint is that my water heater broke",
    ]
    for text in negatives:
        assert not _STATUS_INQUIRY_RE.search(text), f"unexpected match for: {text!r}"


def test_tool_check_status_returns_summary_for_model_to_relay():
    agent = ConversationAgent("t1")
    req = _req(channelIdentity=ChannelIdentityIn(type="email", value="citizen@example.com", verified=False))
    with patch.object(agent._db, "find_by_email", new=AsyncMock(return_value=None)):
        result = _run(agent._tool_check_status(req))

    assert "summary" in result
    assert "don't have any complaints on file" in result["summary"]


def test_assistant_path_check_complaint_status_tool_end_to_end():
    """The assistant decides (via tool-calling) that this is a status
    inquiry, calls check_complaint_status, and relays the summary — never
    touching confirm_identity/submit_complaint for this turn."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-status-3", ticketNumber="TKT-00090", rawText="What's the status of my complaint?",
    )

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        result = await execute_tool("check_complaint_status", {})
        return result["summary"]

    with patch.object(OpenAIAssistantGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "find_by_email", new=AsyncMock(return_value={"master_id": "m-9"})), \
         patch.object(agent._db, "list_tickets", new=AsyncMock(return_value=[
             {"id": "t-9", "ticket_number": "TKT-00080", "category": "technical", "status": "in_progress"},
         ])), \
         patch.object(agent._db, "get_notes", new=AsyncMock(return_value=[])), \
         patch.object(agent._db, "get_messages", new=AsyncMock(return_value=[])), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" not in published_streams
    event_arg = next(c for c in publisher.publish.await_args_list if c.args[0] == "ai.reply.send").args[1]
    assert "TKT-00080" in event_arg["payload"]["messageText"]


# ---------------------------------------------------------------------------
# Conversation persistence — a citizen's reply on an already-open ticket
# (e.g. one moved to pending_customer) and the AI's own reply must both
# appear in the ticket's Conversation timeline, not just whichever turn
# happens to publish complaint.ready. Regression coverage for the reported
# bug: neither showed up when the reply was judged "vague"/conversational.
# ---------------------------------------------------------------------------

def test_persist_inbound_noop_without_ticket_id():
    """Direct/test-endpoint calls with no ticket stub have nothing to persist to."""
    agent = ConversationAgent("t1")
    req = _req(rawText="hello")
    with patch.object(agent._db, "add_message", new=AsyncMock()) as add_message:
        _run(agent._persist_inbound(req, req.rawText))
    add_message.assert_not_awaited()


def test_persist_inbound_noop_for_blank_content():
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-blank")
    with patch.object(agent._db, "add_message", new=AsyncMock()) as add_message:
        _run(agent._persist_inbound(req, "   "))
    add_message.assert_not_awaited()


def test_persist_inbound_swallows_db_errors():
    """Best-effort: Conversation logging must never break the conversation turn."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-err")
    with patch.object(agent._db, "add_message", new=AsyncMock(side_effect=RuntimeError("db-writer down"))):
        _run(agent._persist_inbound(req, "hello"))  # must not raise


def test_rule_based_identity_gate_persists_inbound_and_ai_reply():
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-1", rawText="My meter is broken, please help")
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["identityRequestSent"] is True
    calls = add_message.await_args_list
    assert len(calls) == 2
    assert calls[0].args == ("tkt-1", {
        "tenantId": "t1", "channel": "email", "direction": "inbound",
        "authorType": "user", "content": req.rawText,
    })
    assert calls[1].args[0] == "tkt-1"
    assert calls[1].args[1]["direction"] == "outbound"
    assert calls[1].args[1]["authorType"] == "ai"
    assert calls[1].args[1]["isAiGenerated"] == 1


def test_rule_based_vague_followup_on_open_ticket_persists_inbound_and_ai_reply():
    """Reproduces the reported bug: a short follow-up reply on an
    already-open ticket is judged vague, so it never publishes
    complaint.ready — previously that meant neither the citizen's message
    nor the AI's follow-up question ever reached Conversation."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-2", ticketNumber="TKT-00002",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Still broken",
    )
    known = {"master_id": "m-5", "name": "Ravi Kumar", "email": "ravi@example.com", "phone": "+919876543210"}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=known)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message, \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        publisher.publish = AsyncMock(return_value="1-0")
        resolver_cls.return_value.resolve = AsyncMock(return_value={"masterId": "m-5", "identityStatus": "confirmed"})
        result = _run(agent.process(req))

    assert result["complaintReady"] is False
    calls = add_message.await_args_list
    assert len(calls) == 2
    inbound = next(c for c in calls if c.args[1]["direction"] == "inbound")
    assert inbound.args[0] == "tkt-2"
    assert inbound.args[1]["content"] == "Still broken"
    outbound = next(c for c in calls if c.args[1]["direction"] == "outbound")
    assert outbound.args[1]["authorType"] == "ai"
    assert outbound.args[1]["content"] == FOLLOWUP_QUESTION


def test_rule_based_complaint_ready_does_not_double_persist_inbound():
    """When a turn IS complaint-ready, create_ticket_from_complaint (a
    separate event consumer, not exercised here) is the one that persists
    the message — the agent itself must not also persist it, or the
    citizen's message would appear twice in Conversation."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-3", rawText="My meter is faulty again this week")
    known = {"master_id": "m-7", "name": "Jane Doe", "phone": "9876543210"}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=False), \
         patch.object(agent, "_publisher") as publisher, \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._db, "find_by_email", new=AsyncMock(return_value=known)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert result["complaintReady"] is True
    add_message.assert_not_awaited()


def test_assistant_path_persists_inbound_and_ai_reply_when_no_tool_called():
    """A follow-up reply on an already-resolved ticket where the assistant
    just replies conversationally (no submit_complaint call) — the other
    half of the reported bug, on the Assistants-API path."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-4", ticketNumber="TKT-00004", rawText="It's still not fixed")

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        return "Sorry to hear that — an agent will follow up shortly."

    with patch.object(OpenAIAssistantGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value={
             "identity_status": "confirmed", "master_id": "m-1", "extracted_fields": {"complaint_summary": "x"},
             "questions_asked": 0, "complaint_ready": True,
         })), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message, \
         patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="1-0")
        _run(agent.process(req))

    calls = add_message.await_args_list
    assert len(calls) == 2
    inbound = next(c for c in calls if c.args[1]["direction"] == "inbound")
    assert inbound.args[0] == "tkt-4"
    assert inbound.args[1]["content"] == "It's still not fixed"
    outbound = next(c for c in calls if c.args[1]["direction"] == "outbound")
    assert outbound.args[1]["authorType"] == "ai"
    assert "follow up shortly" in outbound.args[1]["content"]


def test_assistant_path_skips_inbound_persist_when_submit_complaint_called():
    """The complementary case: when the assistant DOES call submit_complaint
    this turn, create_ticket_from_complaint persists the inbound message —
    the agent must not persist it a second time."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-5", rawText="My bill is 3x higher and I never got an explanation")

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        await execute_tool("submit_complaint", {"complaint_summary": "billing issue", "category_hint": "billing"})
        return "Thanks, we've logged your complaint."

    # No mandatory intake fields configured for this tenant/channel (empty
    # list, not absent — see fields_for_channel), so the Feature 15/16 gate
    # never blocks submit_complaint here; this test is about persistence,
    # not the intake gate (covered separately above).
    tenant_config = {"intakeFields": {"email": []}}
    with patch.object(OpenAIAssistantGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value=tenant_config)), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message, \
         patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="1-0")
        _run(agent.process(req))

    calls = add_message.await_args_list
    assert len(calls) == 1  # only the outbound AI reply — inbound left to create_ticket_from_complaint
    assert calls[0].args[1]["direction"] == "outbound"
    assert calls[0].args[1]["authorType"] == "ai"
