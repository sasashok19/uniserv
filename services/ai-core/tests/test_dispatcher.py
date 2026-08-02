"""Unit tests for the channel.message.received dispatcher (Feature 01 x 06 x 18).

Focused on the Feature 18 email coherence pre-check: for email, an
incoherent message must be rejected with NO ticket ever created (not even
a stub) — this runs BEFORE ensure_ticket_stub, so these tests mock
everything downstream and assert it's never reached.
"""

import asyncio
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


def test_auto_generated_email_short_circuits_before_the_coherence_check():
    """A bounce/DSN must never spend an LLM call on the coherence check --
    the existing auto-generated-mail skip must still run first."""
    with patch("app.events.dispatcher.assess_coherence", new=AsyncMock()) as assess, \
         patch("app.events.dispatcher.ensure_ticket_stub", new=AsyncMock()) as ensure_stub:
        _run(_handle_channel_message("t1", _event(
            "email", "Delivery Status Notification (Failure)", identity_value="mailer-daemon@example.org")))

    assess.assert_not_called()
    ensure_stub.assert_not_called()
