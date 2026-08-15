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
from app.conversation.openai_gateway import MAX_TOOL_ROUNDS, OpenAIResponsesGateway
from app.conversation.tools import ASSISTANT_INSTRUCTIONS


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
# Rule-based fallback (no OPENAI_API_KEY configured)
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
# OpenAI Responses path (mocked gateway / tool handlers)
#
# Migrated from the Assistants API in Feature 27 — OpenAI sunsets
# /v1/assistants, /v1/threads and /v1/threads/runs on 26 August 2026.
# ---------------------------------------------------------------------------

def test_openai_gateway_unavailable_without_a_key():
    with patch("app.conversation.openai_gateway.settings") as settings:
        settings.openai_api_key = ""
        assert OpenAIResponsesGateway().is_available() is False


def test_openai_gateway_available_with_a_key_alone():
    """No assistant id is required any more — there is no Assistant object."""
    with patch("app.conversation.openai_gateway.settings") as settings:
        settings.openai_api_key = "sk-test"
        settings.openai_assistant_id = ""
        assert OpenAIResponsesGateway().is_available() is True


def _fake_responses_client(*rounds):
    """A client whose responses.create returns each round in turn."""
    return SimpleNamespace(
        conversations=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id="conv_abc"))),
        responses=SimpleNamespace(create=AsyncMock(side_effect=list(rounds))),
    )


def _function_call(name, arguments="{}", call_id="call_1"):
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


def _reply(text):
    return SimpleNamespace(status="completed", output=[], output_text=text)


def _gateway_settings(settings):
    settings.conversation_state_ttl_hours = 2
    settings.openai_model = "gpt-4o-mini"
    settings.openai_api_key = "sk-test"


def test_openai_gateway_run_turn_drives_the_tool_call_loop_to_a_reply():
    """function_call in output -> execute -> function_call_output back -> reply."""
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(
        SimpleNamespace(status="completed", output=[_function_call("submit_complaint")],
                        output_text=""),
        _reply("Thanks, logged your complaint."),
    )
    valkey = AsyncMock()
    valkey.get.return_value = None
    execute_tool = AsyncMock(return_value={"complaintReady": True})

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        reply = _run(gateway.run_turn("t1", "thread-key", "hello", execute_tool))

    assert reply == "Thanks, logged your complaint."
    execute_tool.assert_awaited_once_with("submit_complaint", {})

    first, second = fake_client.responses.create.await_args_list
    # Round 1 carries the citizen's message; round 2 carries only the result,
    # because the conversation already holds everything else.
    assert first.kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert second.kwargs["input"] == [{
        "type": "function_call_output",
        "call_id": "call_1",
        "output": json.dumps({"complaintReady": True}),
    }]


def test_the_prompt_and_tools_are_sent_on_every_request():
    """The whole point of the migration: instructions come from git, not from a
    remote Assistant object somebody has to remember to re-push."""
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(_reply("hello"))
    valkey = AsyncMock()
    valkey.get.return_value = "conv_existing"

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock(),
                              additional_instructions="company=TNEB"))

    kwargs = fake_client.responses.create.await_args.kwargs
    assert ASSISTANT_INSTRUCTIONS in kwargs["instructions"]
    assert "company=TNEB" in kwargs["instructions"]
    assert kwargs["conversation"] == "conv_existing"
    names = [t["name"] for t in kwargs["tools"]]
    assert {"confirm_identity", "submit_complaint", "check_complaint_status",
            "resolve_duplicate"} <= set(names)
    # Flat shape, not the Assistants/Chat-Completions nested one.
    assert all("function" not in t for t in kwargs["tools"])


def test_a_conversation_is_created_once_and_reused():
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(_reply("hi"))
    valkey = AsyncMock()
    valkey.get.return_value = None

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock()))

    fake_client.conversations.create.assert_awaited_once()
    key, value = valkey.set.await_args.args
    # NOT the old `openai:thread:` prefix — a stale Assistants thread id handed
    # to `conversation=` would fail on every turn until its TTL expired.
    assert key == "openai:conv:t1:thread-key"
    assert value == "conv_abc"
    assert valkey.set.await_args.kwargs["ex"] == 2 * 3600


def test_a_vanished_conversation_starts_a_fresh_one_instead_of_losing_the_message():
    gateway = OpenAIResponsesGateway()

    class NotFound(Exception):
        status_code = 404

    fake_client = SimpleNamespace(
        conversations=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id="conv_new"))),
        responses=SimpleNamespace(create=AsyncMock(side_effect=[NotFound("no such conversation"),
                                                                _reply("still here")])),
    )
    valkey = AsyncMock()
    # The stored id resolves once, then the code deletes it and looks again.
    valkey.get.side_effect = ["conv_expired", None]

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        reply = _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock()))

    assert reply == "still here"
    valkey.delete.assert_awaited_once()
    assert fake_client.responses.create.await_args.kwargs["conversation"] == "conv_new"


def test_an_unrelated_error_is_not_retried_as_a_missing_conversation():
    gateway = OpenAIResponsesGateway()

    class RateLimited(Exception):
        status_code = 429

    fake_client = SimpleNamespace(
        conversations=SimpleNamespace(create=AsyncMock()),
        responses=SimpleNamespace(create=AsyncMock(side_effect=RateLimited("slow down"))),
    )
    valkey = AsyncMock()
    valkey.get.return_value = "conv_1"

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        raised = False
        try:
            _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock()))
        except RateLimited:
            raised = True

    assert raised, "a 429 must propagate, not be retried as a missing conversation"
    assert fake_client.responses.create.await_count == 1


def test_a_failing_tool_is_reported_to_the_model_rather_than_crashing_the_turn():
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(
        SimpleNamespace(status="completed", output=[_function_call("submit_complaint")],
                        output_text=""),
        _reply("Sorry, something went wrong."),
    )
    valkey = AsyncMock()
    valkey.get.return_value = "conv_1"

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        reply = _run(gateway.run_turn("t1", "thread-key", "hi",
                                      AsyncMock(side_effect=RuntimeError("db down"))))

    assert reply == "Sorry, something went wrong."
    sent = fake_client.responses.create.await_args.kwargs["input"][0]
    assert "db down" in sent["output"]


def test_malformed_tool_arguments_become_an_empty_dict():
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(
        SimpleNamespace(status="completed",
                        output=[_function_call("submit_complaint", arguments="{not json")],
                        output_text=""),
        _reply("ok"),
    )
    valkey = AsyncMock()
    valkey.get.return_value = "conv_1"
    execute_tool = AsyncMock(return_value={})

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        _run(gateway.run_turn("t1", "thread-key", "hi", execute_tool))

    execute_tool.assert_awaited_once_with("submit_complaint", {})


def test_a_tool_loop_that_never_settles_is_bounded():
    """Unlike an Assistants run, this loop is ours to bound."""
    gateway = OpenAIResponsesGateway()
    forever = SimpleNamespace(status="completed", output=[_function_call("submit_complaint")],
                              output_text="")
    fake_client = SimpleNamespace(
        conversations=SimpleNamespace(create=AsyncMock()),
        responses=SimpleNamespace(create=AsyncMock(return_value=forever)),
    )
    valkey = AsyncMock()
    valkey.get.return_value = "conv_1"

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        settled = True
        try:
            _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock(return_value={})))
        except RuntimeError as exc:
            settled = "did not settle" not in str(exc)

    assert not settled, "an endless tool loop must be bounded, not run forever"
    assert fake_client.responses.create.await_count == MAX_TOOL_ROUNDS


def test_an_incomplete_response_is_an_error_not_an_empty_reply():
    gateway = OpenAIResponsesGateway()
    fake_client = _fake_responses_client(
        SimpleNamespace(status="incomplete", output=[], output_text=""))
    valkey = AsyncMock()
    valkey.get.return_value = "conv_1"

    with patch.object(OpenAIResponsesGateway, "client", new=fake_client), \
         patch("app.conversation.openai_gateway.get_valkey", return_value=valkey), \
         patch("app.conversation.openai_gateway.settings") as settings:
        _gateway_settings(settings)
        message = ""
        try:
            _run(gateway.run_turn("t1", "thread-key", "hi", AsyncMock()))
        except RuntimeError as exc:
            message = str(exc)

    assert "status=incomplete" in message


def test_nothing_still_calls_the_sunset_assistants_endpoints():
    """OpenAI removes /v1/assistants, /v1/threads and /v1/threads/runs on
    26 August 2026. A stray `client.beta.threads` anywhere in ai-core would go
    from working to a hard failure on that date with no warning."""
    import pathlib
    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("beta.threads", "beta.assistants"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, offenders


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


# ---------------------------------------------------------------------------
# Feature 17 fix: providedFields bridge (live-testing regression, 2026-08-02
# transcript). A verified WhatsApp citizen gave their name/email in casual,
# unlabeled phrasing ("Ashok, miscemail19@gmail.com"; later "I already
# provided the name… ashok") — the label-anchored regex never matched either
# reply, so identity_status stayed "pending" forever even though the model
# itself correctly understood who was writing in. providedFields lets the
# model hand that understanding to the gate directly instead of making us
# re-derive it from raw text.
# ---------------------------------------------------------------------------

def test_merge_provided_fields_maps_label_to_key_and_validates():
    from app.conversation.agent import _merge_provided_fields
    state = {}
    _merge_provided_fields(state, {"Name": "Ashok", "Email": "miscemail19@gmail.com"}, catalog_for_tenant(None))

    assert state["intake"]["name"] == {"value": "Ashok", "valid": True, "source": "extracted"}
    assert state["intake"]["email"] == {
        "value": "miscemail19@gmail.com", "valid": True, "source": "extracted",
    }


def test_merge_provided_fields_ignores_unknown_labels_and_blank_values():
    from app.conversation.agent import _merge_provided_fields
    state = {}
    _merge_provided_fields(state, {"NotARealLabel": "whatever", "Name": "   "}, catalog_for_tenant(None))
    assert state.get("intake", {}) == {}


def test_merge_provided_fields_overwrites_earlier_regex_extraction():
    from app.conversation.agent import _merge_provided_fields
    state = {"intake": {"name": {"value": None, "valid": True, "source": None}}}
    _merge_provided_fields(state, {"Name": "Ashok"}, catalog_for_tenant(None))
    assert state["intake"]["name"]["value"] == "Ashok"


def test_tool_confirm_identity_provided_fields_satisfies_gate_from_casual_phrasing():
    """The exact reported bug, reproduced directly against the tool handler:
    the model calls confirm_identity with providedFields={"Name": "Ashok"} —
    a value that "Ashok, miscemail19@gmail.com" (no literal "name"/"email"
    words) could never have satisfied via regex alone — and the ticket now
    correctly promotes to confirmed instead of staying pending forever."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-ashok-1",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+918939012727", verified=True),
        rawText="Ashok, miscemail19@gmail.com",
    )
    state = {"identity_status": "pending", "master_id": None, "intake": {}}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-ashok", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "providedFields": {"Name": "Ashok", "Email": "miscemail19@gmail.com"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["identity_status"] == "confirmed"
    assert result["missingFields"] == []
    assert update_ticket.await_args.args[1]["identityStatus"] == "confirmed"
    # The full (untruncated) email now also reaches the identity resolver.
    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedName == "Ashok"


def test_tool_confirm_identity_provided_fields_satisfies_gate_from_ellipsis_phrasing():
    """The third message in the same transcript: "I already provided the
    name… ashok" — contains the word "name" but followed by an ellipsis, not
    a recognised separator, so the regex still wouldn't have matched. Model
    understood it regardless and can supply it via providedFields."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-ashok-1",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+918939012727", verified=True),
        rawText="I already provided the name… ashok",
    )
    state = {"identity_status": "pending", "master_id": None, "intake": {
        "email": {"value": "miscemail19@gmail.com", "valid": True, "source": "extracted"},
    }}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-ashok", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state, {"declaredAnonymous": False, "providedFields": {"Name": "ashok"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["identity_status"] == "confirmed"
    assert result["missingFields"] == []


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

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
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

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
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


# ---------------------------------------------------------------------------
# Feature 18: is_coherent gate on submit_complaint — refuses to file an
# unclear/likely-mistyped complaint the model itself flagged, regardless of
# channel (email's HARD no-ticket-at-all reject happens earlier, in
# dispatcher.py, before a stub even exists — see test_dispatcher.py; by the
# time submit_complaint runs a stub already exists for every channel, so
# what's left here is "ask for confirmation," which applies uniformly).
# ---------------------------------------------------------------------------

def test_assistant_path_refuses_submit_complaint_when_model_flags_incoherent():
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-incoherent-1",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Put not closed",
    )

    captured = {}

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        await execute_tool("confirm_identity", {"declaredAnonymous": False})
        captured["result"] = await execute_tool(
            "submit_complaint",
            {"complaint_summary": "Put not closed", "category_hint": "other", "is_coherent": False},
        )
        return "Just to confirm — did you mean a pit/manhole that hasn't been closed?"

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value={
             "master_id": "m-1", "name": "Ashok", "email": "ashok@example.com",
         })), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher, \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    assert captured["result"]["error"] == "unclear_complaint"
    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" not in published_streams
    assert result["complaintReady"] is False


def test_assistant_path_submits_complaint_when_model_confirms_coherent():
    """Positive case: once the citizen confirms/clarifies and the model
    reports is_coherent=true, submit_complaint proceeds as normal."""
    agent = ConversationAgent("t1")
    req = _req(
        ticketId="tkt-incoherent-2",
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        rawText="Yes, the pit near my house hasn't been closed",
    )

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        await execute_tool("confirm_identity", {"declaredAnonymous": False})
        await execute_tool(
            "submit_complaint",
            {"complaint_summary": "An open pit near the citizen's house hasn't been closed",
             "category_hint": "other", "is_coherent": True},
        )
        return "Thanks, we've logged your complaint."

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value=None)), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value={
             "master_id": "m-1", "name": "Ashok", "email": "ashok@example.com",
         })), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher, \
         patch("app.conversation.agent.IdentityResolver") as resolver_cls:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" in published_streams
    assert result["complaintReady"] is True


def test_assistant_path_submit_complaint_gate_defaults_to_coherent_when_field_omitted():
    """Defensive default: if the model somehow omits is_coherent despite it
    being a required schema field, the CODE-LEVEL gate must not refuse —
    default to coherent rather than blocking every complaint that happens
    to omit it."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-incoherent-3", rawText="My bill is wrong")

    async def fake_run_turn(tenant_id, state_key, user_message, execute_tool, additional_instructions):
        result = await execute_tool(
            "submit_complaint", {"complaint_summary": "My bill is wrong", "category_hint": "billing"})
        assert "error" not in result
        return "Thanks, we've logged your complaint."

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
         patch.object(agent, "_load_state", new=AsyncMock(return_value={
             "identity_status": "confirmed", "master_id": "m-1", "extracted_fields": {},
             "questions_asked": 0, "complaint_ready": False,
         })), \
         patch.object(agent, "_find_known_identity", new=AsyncMock(return_value={
             "master_id": "m-1", "name": "Jane Doe",
         })), \
         patch.object(agent._db, "get_tenant_config", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "get_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent, "_save_state", new=AsyncMock()), \
         patch.object(agent._openai, "run_turn", new=AsyncMock(side_effect=fake_run_turn)), \
         patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent, "_publisher") as publisher:
        publisher.publish = AsyncMock(return_value="1-0")
        result = _run(agent.process(req))

    published_streams = [call.args[0] for call in publisher.publish.await_args_list]
    assert "complaint.ready" in published_streams
    assert result["complaintReady"] is True


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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=False), \
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

    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
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
    with patch.object(OpenAIResponsesGateway, "is_available", return_value=True), \
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


# ---------------------------------------------------------------------------
# Feature 20: mistyped email must not reach the identity profile, and partial
# intake must reach the ticket.
#
# Reported transcript (+918939014142): "Nithya / Nithya@gmaill.com /
# 56784567". The typo domain was accepted and written to the profile, and the
# service id — the one answer that WAS good — was recorded nowhere, because
# the only place it was ever written was ticket creation, which never
# happened.
# ---------------------------------------------------------------------------

_WHATSAPP_ID = ChannelIdentityIn(type="phone", value="+918939014142", verified=True)


def test_tool_confirm_identity_keeps_a_typo_email_off_the_identity_profile():
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="Nithya, Nithya@gmaill.com, 56784567")
    state = {"identity_status": "pending", "master_id": None, "intake": {}}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-nithya", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "identityType": "email", "identityValue": "Nithya@gmaill.com",
             "providedFields": {"Name": "Nithya", "Email": "Nithya@gmaill.com",
                                "Service/Customer ID": "56784567"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedEmail is None          # the typo never reaches the profile
    assert resolve_req.confirmedName == "Nithya"       # the good answers still do
    # The gate holds the ticket back and asks about the address, naming both spellings.
    assert state["identity_status"] == "pending"
    assert len(result["missingFields"]) == 1
    assert "Nithya@gmail.com" in result["missingFields"][0]
    assert "Nithya@gmaill.com" in result["missingFields"][0]
    # ...and the service id is written onto the stub on this very turn.
    assert update_ticket.await_args.args[1]["serviceId"] == "56784567"
    assert update_ticket.await_args.args[1]["identityStatus"] == "pending"


def test_tool_confirm_identity_accepts_the_corrected_email_and_confirms_the_same_ticket():
    """The retry turn: same stub (same ticketId), corrected address — the gate
    clears, the profile finally gets an email, and the EXISTING ticket is what
    moves to confirmed."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="dharshini.s.raj@gmail.com")
    state = {"identity_status": "pending", "master_id": "m-nithya", "intake": {
        "name": {"value": "Nithya", "valid": True, "source": "extracted"},
        "serviceId": {"value": "56784567", "valid": True, "source": "extracted"},
        "email": {"value": "Nithya@gmaill.com", "valid": False, "source": "extracted"},
    }}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket:
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-nithya", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False,
             "providedFields": {"Email": "dharshini.s.raj@gmail.com"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert result["missingFields"] == []
    assert state["identity_status"] == "confirmed"
    resolve_req = resolver_cls.return_value.resolve.await_args.args[0]
    assert resolve_req.confirmedEmail == "dharshini.s.raj@gmail.com"
    assert update_ticket.await_args.args[0] == "tkt-16"          # the SAME ticket, not a new one
    assert update_ticket.await_args.args[1]["identityStatus"] == "confirmed"


def test_ticket_fields_from_intake_ignores_unvalidated_and_secondhand_values():
    from app.conversation.agent import _ticket_fields_from_intake
    assert _ticket_fields_from_intake({}) == {}
    assert _ticket_fields_from_intake(
        {"serviceId": {"value": "56784567", "valid": True, "source": "extracted"}}) == {"serviceId": "56784567"}
    # Invalid, or already-on-file rather than freshly written -> not re-stamped.
    assert _ticket_fields_from_intake({"serviceId": {"value": "??", "valid": False, "source": "extracted"}}) == {}
    assert _ticket_fields_from_intake({"serviceId": {"value": "1", "valid": True, "source": "known"}}) == {}
    # Identity attributes belong to the profile, not to a ticket column.
    assert _ticket_fields_from_intake({"name": {"value": "Nithya", "valid": True, "source": "extracted"}}) == {}


def _queried_email_state(**overrides) -> dict:
    state = {"identity_status": "pending", "master_id": "m-1",
             "queried_intake": {"email": {"asked": "nithya@gmaill.com"}},
             "intake": {
                 "name": {"value": "Nithya", "valid": True, "source": "extracted"},
                 "email": {"value": "nithya@gmaill.com", "valid": False, "source": "extracted"},
             }}
    state.update(overrides)
    return state


def test_yes_to_the_typo_question_takes_the_SUGGESTION_not_the_typo():
    """The citizen is asked 'you sent "nithya@gmaill.com"; did you mean
    "nithya@gmail.com"?' — so "yes" means TAKE THE SUGGESTION. Reading it the
    other way round would re-introduce, on the single most likely reply, the
    exact typo this whole feature exists to catch."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="yes that is correct")
    state = _queried_email_state()

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "identityType": "email", "identityValue": "nithya@gmaill.com"},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert result["missingFields"] == []
    assert state["intake"]["email"]["value"] == "nithya@gmail.com"
    assert resolver_cls.return_value.resolve.await_args.args[0].confirmedEmail == "nithya@gmail.com"
    assert state["queried_intake"]["email"]["resolved"] == "nithya@gmail.com"


def test_resending_the_same_address_keeps_it_even_though_the_validator_refused_it():
    """The other half of "confirm or correct": the domain list is a heuristic
    and the citizen is the authority on their own address, so sending it again
    unchanged overrules us. Without this an unusual-but-real domain would be
    re-asked forever — a worse failure than the typo."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="no, it really is nithya@gmaill.com")
    state = _queried_email_state()

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "identityType": "email", "identityValue": "nithya@gmaill.com"},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert result["missingFields"] == []
    assert state["intake"]["email"]["value"] == "nithya@gmaill.com"
    assert resolver_cls.return_value.resolve.await_args.args[0].confirmedEmail == "nithya@gmaill.com"


def test_an_affirmation_word_inside_ordinary_complaint_prose_settles_nothing():
    """"right"/"same"/"it is" turn up constantly in complaint text, and
    `queried_intake` persists across turns — so the affirmation check is
    narrow AND only consulted on a short message. A later, unrelated turn must
    not silently promote a refused address."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="the transformer on the right side is sparking and it is still not fixed")
    state = _queried_email_state()

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state, {"declaredAnonymous": False},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["intake"]["email"]["valid"] is False
    assert len(result["missingFields"]) == 1
    assert resolver_cls.return_value.resolve.await_args.args[0].confirmedEmail is None


def test_a_refused_identity_value_email_is_recorded_so_the_citizen_is_told_why():
    """The reported transcript's shape: the model reports the address as the
    IDENTITY value rather than via providedFields. It used to be validated,
    dropped, and never written anywhere — so the citizen was told only "we
    still need: Email", with no hint that the address they had just sent was
    the problem, and retyped the same typo indefinitely."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="Nithya@gmaill.com")
    state = {"identity_status": "pending", "master_id": None,
             "intake": {"name": {"value": "Nithya", "valid": True, "source": "extracted"}}}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "identityType": "email", "identityValue": "Nithya@gmaill.com"},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["intake"]["email"] == {"value": "Nithya@gmaill.com", "valid": False, "source": "extracted"}
    assert len(result["missingFields"]) == 1
    assert "Nithya@gmail.com" in result["missingFields"][0]
    assert state["queried_intake"] == {"email": {"asked": "Nithya@gmaill.com"}}


def test_confirm_identity_keeps_asking_when_the_model_merely_resends_a_queried_value():
    """The model is instructed to resend every value it knows on every
    confirm_identity call, so a bare resend is not evidence of anything — only
    the CITIZEN's own words (an affirmation, or retyping the address) count."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="my service id is 56784567")
    state = {"identity_status": "pending", "master_id": "m-1",
             "queried_intake": {"email": {"asked": "nithya@gmaill.com"}},
             "intake": {
                 "name": {"value": "Nithya", "valid": True, "source": "extracted"},
                 "email": {"value": "nithya@gmaill.com", "valid": False, "source": "extracted"},
             }}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "providedFields": {"Email": "nithya@gmaill.com"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert len(result["missingFields"]) == 1
    assert "nithya@gmail.com" in result["missingFields"][0]
    assert state["identity_status"] == "pending"
    assert resolver_cls.return_value.resolve.await_args.args[0].confirmedEmail is None


def test_confirm_identity_records_which_values_it_queried():
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID,
               rawText="Nithya nithya@gmaill.com")
    state = {"identity_status": "pending", "master_id": None, "intake": {}}

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False,
             "providedFields": {"Name": "Nithya", "Email": "nithya@gmaill.com"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["queried_intake"] == {"email": {"asked": "nithya@gmaill.com"}}


def test_the_correction_survives_the_model_resending_the_original_later_in_the_turn():
    """Ordering regression. `_update_intake_and_get_missing` runs at the top of
    a turn and settles the citizen's "yes"; a few lines later the model's
    confirm_identity call resends the ORIGINAL address (it is told to resend
    everything it knows). Without remembering the decision, that merge quietly
    undoes the correction and the typo is what gets stored."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="tkt-16", channel="whatsapp", channelIdentity=_WHATSAPP_ID, rawText="yes")
    state = _queried_email_state()

    with patch.object(agent, "_find_known_identity", new=AsyncMock(return_value=None)):
        missing = _run(agent._update_intake_and_get_missing(
            req, state, DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))
    assert missing == []
    assert state["intake"]["email"]["value"] == "nithya@gmail.com"

    with patch("app.conversation.agent.IdentityResolver") as resolver_cls, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})):
        resolver_cls.return_value.resolve = AsyncMock(
            return_value={"masterId": "m-1", "identityStatus": "confirmed"})
        result = _run(agent._tool_confirm_identity(
            req, state,
            {"declaredAnonymous": False, "providedFields": {"Email": "nithya@gmaill.com"}},
            DEFAULT_INTAKE_FIELDS["whatsapp"], catalog_for_tenant(None)))

    assert state["intake"]["email"]["value"] == "nithya@gmail.com"   # the correction held
    assert result["missingFields"] == []
    assert resolver_cls.return_value.resolve.await_args.args[0].confirmedEmail == "nithya@gmail.com"


def test_a_second_bad_address_gets_its_own_question():
    """A settled decision must not shadow the next attempt: if the citizen
    later sends a different address that is also refused, that one has to be
    queried in its own right, or their answer to it goes nowhere."""
    agent = ConversationAgent("t1")
    state = {"identity_status": "pending", "master_id": "m-1",
             "queried_intake": {"email": {"asked": "nithya@gmaill.com", "resolved": "nithya@gmail.com"}},
             "intake": {"name": {"value": "Nithya", "valid": True, "source": "extracted"},
                        "email": {"value": "nithya@yahooo.com", "valid": False, "source": "extracted"}}}

    from app.conversation.agent import _remember_queried_values
    _remember_queried_values(state, ["a confirmed Email ..."])

    assert state["queried_intake"]["email"] == {"asked": "nithya@yahooo.com"}


# ---------------------------------------------------------------------------
# Feature 22: suspected-duplicate resolution. Routing can flag "this MIGHT
# continue TKT-000xx" when the message omits the detail that would settle it
# (e.g. "water logging" while "water logging in Madambakkam" is open). Nothing
# merges on that suspicion alone — the citizen is asked, and their answer is
# what acts.
# ---------------------------------------------------------------------------

_SUSPECTED = {"id": "t-42", "ticketNumber": "TKT-00042", "summary": "Water logging in Madambakkam"}


def test_confirmed_duplicate_merges_appends_and_records_an_audit_event():
    agent = ConversationAgent("t1")
    req = _req(ticketId="t-new", channel="email", rawText="Yes, same one in Madambakkam",
               suspectedDuplicateOf=_SUSPECTED)

    with patch.object(agent._db, "add_message", new=AsyncMock(return_value={})) as add_message, \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})) as update_ticket, \
         patch.object(agent._db, "add_event", new=AsyncMock(return_value={})) as add_event:
        result = _run(agent._tool_resolve_duplicate(req, {"isDuplicate": True}))

    assert result["isDuplicate"] is True
    assert result["mergedInto"] == "TKT-00042"
    # The citizen's message lands on the ORIGINAL, not just on the closed stub.
    assert add_message.await_args.args[0] == "t-42"
    # ...and this ticket takes the existing duplicate treatment.
    assert update_ticket.await_args.args[0] == "t-new"
    assert update_ticket.await_args.args[1] == {
        "isDuplicate": 1, "parentTicketId": "t-42", "status": "closed"}
    # ...and BOTH trails record it: the original says what it absorbed, and
    # this ticket says where it went (otherwise its trail shows an
    # unexplained close).
    written = {c.args[0]: c.args[1] for c in add_event.await_args_list}
    assert written["t-42"]["eventType"] == "ticket.duplicate_merged"
    assert written["t-42"]["meta"]["mergedFromId"] == "t-new"
    assert written["t-new"]["eventType"] == "ticket.duplicate_confirmed"
    assert written["t-new"]["meta"]["duplicateOfNumber"] == "TKT-00042"


def test_rejected_duplicate_leaves_both_tickets_alone():
    agent = ConversationAgent("t1")
    req = _req(ticketId="t-new", channel="email", rawText="No, this one is in Tambaram",
               suspectedDuplicateOf=_SUSPECTED)

    with patch.object(agent._db, "add_message", new=AsyncMock()) as add_message, \
         patch.object(agent._db, "update_ticket", new=AsyncMock()) as update_ticket:
        result = _run(agent._tool_resolve_duplicate(req, {"isDuplicate": False}))

    assert result["isDuplicate"] is False
    add_message.assert_not_called()
    update_ticket.assert_not_called()


def test_resolve_duplicate_refuses_when_nothing_was_flagged():
    """The model must not be able to merge tickets on its own initiative — the
    tool only acts on a suspicion routing actually raised."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="t-new", channel="email", rawText="merge these please")

    with patch.object(agent._db, "update_ticket", new=AsyncMock()) as update_ticket:
        result = _run(agent._tool_resolve_duplicate(req, {"isDuplicate": True}))

    assert result["error"] == "no_suspected_duplicate"
    update_ticket.assert_not_called()


def test_merge_survives_a_failed_audit_write():
    """The audit line is best-effort: the tickets are already merged by the
    time it runs, and losing it must not fail the citizen's turn."""
    agent = ConversationAgent("t1")
    req = _req(ticketId="t-new", channel="email", rawText="yes same", suspectedDuplicateOf=_SUSPECTED)

    with patch.object(agent._db, "add_message", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "update_ticket", new=AsyncMock(return_value={})), \
         patch.object(agent._db, "add_event", new=AsyncMock(side_effect=RuntimeError("db down"))):
        result = _run(agent._tool_resolve_duplicate(req, {"isDuplicate": True}))

    assert result["isDuplicate"] is True


def test_suspected_duplicate_reaches_the_models_per_turn_instructions():
    """The model has to ask a SPECIFIC question ("...in Madambakkam?"), so it
    is given the other complaint's own words, not just a ticket number."""
    req = _req(suspectedDuplicateOf=_SUSPECTED)
    state = {"identity_status": "confirmed", "questions_asked": 0, "complaint_ready": False}
    rendered = ConversationAgent._render_additional_instructions(
        req, state, DEFAULT_INTAKE_FIELDS["email"], 2, catalog_for_tenant(None), [])

    assert "POSSIBLE DUPLICATE" in rendered
    assert "TKT-00042" in rendered
    assert "Water logging in Madambakkam" in rendered
    assert "resolve_duplicate" in rendered


def test_no_duplicate_hint_when_routing_did_not_flag_one():
    req = _req()
    state = {"identity_status": "confirmed", "questions_asked": 0, "complaint_ready": False}
    rendered = ConversationAgent._render_additional_instructions(
        req, state, DEFAULT_INTAKE_FIELDS["email"], 2, catalog_for_tenant(None), [])

    assert "POSSIBLE DUPLICATE" not in rendered
