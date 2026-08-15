"""Unit tests for the channel.message.received dispatcher (Feature 01 x 06 x 18).

Focused on the Feature 18 email coherence pre-check: for email, an
incoherent message must be rejected with NO ticket ever created (not even
a stub) — this runs BEFORE ensure_ticket_stub, so these tests mock
everything downstream and assert it's never reached.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.events.dispatcher import REJECTED_COMPLAINT_MESSAGE, _handle_channel_message


def _run(coro):
    return asyncio.run(coro)


def _event(channel: str, raw_text: str, identity_value: str = "citizen@example.org", identity_type: str = "email"):
    return {
        "traceId": "tr-1",
        "payload": {
            "channel": channel,
            "channelIdentity": {"type": identity_type, "value": identity_value, "verified": channel == "whatsapp"},
            "rawText": raw_text,
        },
    }


def test_email_rejected_as_incoherent_never_creates_a_ticket_stub():
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock(
            return_value={"coherent": False, "reason": "gibberish"})), \
         patch("app.events.dispatcher.send_email", new=AsyncMock()) as send_email, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock()) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls:
        _run(_handle_channel_message("t1", _event("email", "asdkfj qwoeiru xyz")))

    ensure_stub.assert_not_called()
    agent_cls.return_value.process.assert_not_called()
    send_email.assert_awaited_once_with(
        "citizen@example.org", "Re: your message to UniServe", REJECTED_COMPLAINT_MESSAGE, "tr-1")


def test_email_judged_coherent_proceeds_to_ticket_stub_as_normal():
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock(
            return_value={"coherent": True, "reason": None})), \
         patch("app.events.dispatcher.send_email", new=AsyncMock()) as send_email, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock(
             return_value={"id": "t-1", "ticketNumber": "TKT-00001"})) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls:
        agent_cls.return_value.process = AsyncMock(return_value={"complaintReady": False})
        _run(_handle_channel_message("t1", _event("email", "No power in my area")))

    ensure_stub.assert_awaited_once()
    agent_cls.return_value.process.assert_awaited_once()
    send_email.assert_not_called()


def test_email_coherence_check_unavailable_fails_open_and_proceeds():
    """Best-effort: if the LLM check itself can't run (returns None), never
    block a real complaint — proceed exactly as if it were coherent."""
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock(return_value=None)), \
         patch("app.events.dispatcher.send_email", new=AsyncMock()) as send_email, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock(
             return_value={"id": "t-2", "ticketNumber": "TKT-00002"})) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls:
        agent_cls.return_value.process = AsyncMock(return_value={"complaintReady": False})
        _run(_handle_channel_message("t1", _event("email", "My bill is wrong")))

    ensure_stub.assert_awaited_once()
    send_email.assert_not_called()


def test_whatsapp_never_runs_the_coherence_precheck():
    """The gate is email-specific -- WhatsApp handles unclear complaints
    interactively (see ConversationAgent's is_coherent tool gate), not via
    this pre-stub rejection."""
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock()) as assess, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock(
             return_value={"id": "t-3", "ticketNumber": "TKT-00003"})), \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls:
        agent_cls.return_value.process = AsyncMock(return_value={"complaintReady": False})
        _run(_handle_channel_message("t1", _event(
            "whatsapp", "Put not closed", identity_value="+919876543210", identity_type="phone")))

    assess.assert_not_called()


def test_in_reply_to_is_forwarded_from_payload_to_ensure_ticket_stub(fake_valkey):
    """Feature 19: the WhatsApp adapter's context.id (or email's
    In-Reply-To) rides in the event payload as inReplyTo -- must reach
    ensure_ticket_stub as in_reply_to, or swipe-reply matching is dead on
    arrival regardless of how well the intake-side logic is written.

    Feature 26 put the WhatsApp menu in front of this, so the session is placed
    in the intake flow first — that is the state in which a WhatsApp message
    reaches the routing ladder at all now.
    """
    thread_key = "whatsapp:+919876543213"
    fake_valkey.store[f"wamenu:t1:{thread_key}"] = json.dumps({"state": "intake"})
    with patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock(
            return_value={"id": "t-14", "ticketNumber": "TKT-00014"})) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={})):
        agent_cls.return_value.process = AsyncMock(return_value={"complaintReady": False})
        # Mocking the class also mocks its static _thread_key, which the
        # dispatcher uses to find the menu session. Give it the real value back.
        agent_cls._thread_key.return_value = thread_key
        event = _event("whatsapp", "It happens around 11PM",
                        identity_value="+919876543213", identity_type="phone")
        event["payload"]["inReplyTo"] = "wamid.ORIGINAL123"
        _run(_handle_channel_message("t1", event))

    assert ensure_stub.await_args.kwargs["in_reply_to"] == "wamid.ORIGINAL123"


def test_a_whatsapp_first_contact_gets_the_welcome_menu_and_creates_no_ticket(fake_valkey):
    """Feature 26, the headline behaviour: the AI speaks first.

    Note the deliberate consequence — a swipe-reply from a citizen with no live
    session gets the menu rather than routing straight to its ticket. That is
    what "strict menu" means, and it is why the menu is switchable per tenant
    (`whatsappMenu.enabled`).
    """
    with patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock()) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls, \
         patch("app.events.dispatcher.deliver_reply", new=AsyncMock()) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={"landingPage": {"brandName": "TNEB"}})):
        _run(_handle_channel_message("t1", _event(
            "whatsapp", "hi", identity_value="+919876543299", identity_type="phone")))

    ensure_stub.assert_not_called()
    agent_cls.return_value.process.assert_not_called()
    payload = deliver.await_args.args[0]
    assert "Welcome to TNEB" in payload["messageText"]
    # Feature 28: the options ride as tappable buttons, and the # escape as the footer.
    assert [b["title"] for b in payload["buttons"]] == ["Ticket status", "New ticket", "End chat"]
    assert "#" in payload["footer"], "every message must offer the way back to the main menu"


def test_the_menu_can_be_switched_off_per_tenant(fake_valkey):
    """With the menu disabled the pre-Feature-26 behaviour returns exactly:
    straight into the routing ladder, no welcome, no session."""
    with patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock(
            return_value={"id": "t-9", "ticketNumber": "TKT-00009"})) as ensure_stub, \
         patch("app.events.dispatcher.ConversationAgent") as agent_cls, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={"whatsappMenu": {"enabled": False}})):
        agent_cls.return_value.process = AsyncMock(return_value={"complaintReady": False})
        _run(_handle_channel_message("t1", _event(
            "whatsapp", "power cut", identity_value="+919876543298", identity_type="phone")))

    ensure_stub.assert_called_once()
    assert not fake_valkey.store, "a disabled menu must not create session state"


def test_auto_generated_email_short_circuits_before_the_coherence_check():
    """A bounce/DSN must never spend an LLM call on the coherence check --
    the existing auto-generated-mail skip must still run first."""
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock()) as assess, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock()) as ensure_stub:
        _run(_handle_channel_message("t1", _event(
            "email", "Delivery Status Notification (Failure)", identity_value="mailer-daemon@example.org")))

    assess.assert_not_called()
    ensure_stub.assert_not_called()


# --- Feature 26: the "#" hint on AI replies --------------------------------

def test_an_ai_reply_during_intake_carries_the_menu_hint(fake_valkey):
    """"In all conversation it should mention press # to return to main menu."
    Applied deterministically here rather than asked of the assistant — a prompt
    instruction is followed most of the time, and "most of the time" is not what
    "in all conversation" means."""
    from app.events.dispatcher import _handle_ai_reply_send

    fake_valkey.store["wamenu:t1:whatsapp:+919000000001"] = json.dumps({"state": "intake"})
    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={})):
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "whatsapp", "channelIdentityValue": "+919000000001",
            "messageText": "Could you tell me which street?"}}))

    assert "press # at any time" in deliver.await_args.args[0]["messageText"]


def test_the_hint_is_not_added_to_email(fake_valkey):
    from app.events.dispatcher import _handle_ai_reply_send

    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver:
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "email", "channelIdentityValue": "c@example.org",
            "messageText": "Could you tell me which street?"}}))

    assert "#" not in deliver.await_args.args[0]["messageText"]


def test_the_hint_is_added_even_without_a_menu_session(fake_valkey):
    """Feature 28: a citizen answering an agent's follow-up has no menu session,
    and `#` still works for them — handle_inbound treats it as the top-level
    escape from any state. Gating the hint on a session hid the way out from
    exactly the people most likely to want it."""
    from app.events.dispatcher import _handle_ai_reply_send

    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={})):
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "whatsapp", "channelIdentityValue": "+919000000002",
            "messageText": "Which street?"}}))

    assert "press # at any time" in deliver.await_args.args[0]["messageText"]


def test_the_hint_is_not_added_when_the_menu_is_disabled(fake_valkey):
    """A tenant that switched the menu off has no main menu to return to."""
    from app.events.dispatcher import _handle_ai_reply_send

    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={"whatsappMenu": {"enabled": False}})):
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "whatsapp", "channelIdentityValue": "+919000000002",
            "messageText": "Which street?"}}))

    assert deliver.await_args.args[0]["messageText"] == "Which street?"


def test_the_hint_is_never_duplicated(fake_valkey):
    from app.events.dispatcher import _handle_ai_reply_send

    fake_valkey.store["wamenu:t1:whatsapp:+919000000003"] = json.dumps({"state": "intake"})
    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(return_value={})):
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "whatsapp", "channelIdentityValue": "+919000000003",
            "messageText": "Which street?\n\nYou can press # at any time to return to the main menu."}}))

    assert deliver.await_args.args[0]["messageText"].count("press #") == 1


def test_a_delivery_failure_is_never_caused_by_the_hint(fake_valkey):
    """A missing hint is cosmetic; a message that never reaches the citizen is not."""
    from app.events.dispatcher import _handle_ai_reply_send

    fake_valkey.store["wamenu:t1:whatsapp:+919000000004"] = json.dumps({"state": "intake"})
    with patch("app.events.dispatcher.deliver_reply",
               new=AsyncMock(return_value={"delivered": True})) as deliver, \
         patch("app.identity.db_client.DbWriterClient.get_tenant_config",
               new=AsyncMock(side_effect=RuntimeError("db down"))):
        _run(_handle_ai_reply_send("t1", {"traceId": "tr-h", "payload": {
            "channel": "whatsapp", "channelIdentityValue": "+919000000004",
            "messageText": "Which street?"}}))

    assert deliver.await_args.args[0]["messageText"] == "Which street?"
