"""Unit tests for ConversationAgent._thread_key (Feature 15 regression).

A citizen's brand-new, unrelated email was being folded into an old ticket
because the email fallback collapsed to "email:<address>" for every message
without a real In-Reply-To header — identical regardless of subject/content.
"""

from app.conversation.agent import ChannelIdentityIn, ConversationAgent, TestEventRequest


def _req(**overrides):
    base = dict(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="citizen@example.com", verified=False),
        rawText="hello",
    )
    base.update(overrides)
    return TestEventRequest(**base)


def test_thread_key_uses_real_thread_id_when_present():
    req = _req(threadId="in-reply-to-value")
    assert ConversationAgent._thread_key(req) == "in-reply-to-value"


def test_thread_key_uses_message_id_for_email_without_thread_id():
    """The fix: a fresh email (no In-Reply-To) gets a key unique to THIS
    message, not one shared with every other email from the same address."""
    req = _req(messageId="msg-abc-123")
    assert ConversationAgent._thread_key(req) == "email:msg-abc-123"


def test_thread_key_two_unrelated_emails_get_different_keys():
    first = _req(messageId="msg-1")
    second = _req(messageId="msg-2")
    assert ConversationAgent._thread_key(first) != ConversationAgent._thread_key(second)


def test_thread_key_falls_back_to_address_when_no_message_id_captured():
    """Defensive fallback only — real inbound email always has a Message-ID."""
    req = _req(messageId=None)
    assert ConversationAgent._thread_key(req) == "email:citizen@example.com"


def test_thread_key_whatsapp_still_uses_persistent_address_based_key():
    """WhatsApp has no subject/message-id concept; one thread per phone
    number for the life of the conversation is correct and must not change."""
    req = _req(
        channel="whatsapp",
        channelIdentity=ChannelIdentityIn(type="phone", value="+919876543210", verified=True),
        messageId="whatsapp-has-no-message-id-but-even-if-set-should-be-ignored",
    )
    assert ConversationAgent._thread_key(req) == "whatsapp:+919876543210"


# --- _conv_key: stable memory key across a multi-turn email exchange ---------


def test_conv_key_prefers_stable_ticket_id():
    """Conversation memory keys on the ticket, so the citizen's reply (which
    threads off our identity-request email, giving it a DIFFERENT thread_key)
    still finds the saved complaint instead of starting over."""
    req = _req(ticketId="tkt-uuid-1", messageId="msg-1")
    assert ConversationAgent._conv_key(req) == "ticket:tkt-uuid-1"


def test_conv_key_stable_across_turns_with_different_message_ids():
    """Two turns of the SAME conversation (original complaint, then the reply
    with identity) have different email thread_keys but the same ticket, so
    they must resolve to the same conversation-memory key."""
    turn1 = _req(ticketId="tkt-uuid-9", messageId="original-msg", threadId=None)
    turn2 = _req(ticketId="tkt-uuid-9", messageId="reply-msg", threadId="our-identity-request-msg-id")
    assert ConversationAgent._conv_key(turn1) == ConversationAgent._conv_key(turn2) == "ticket:tkt-uuid-9"
    # ...even though the raw email thread_keys differ.
    assert ConversationAgent._thread_key(turn1) != ConversationAgent._thread_key(turn2)


def test_conv_key_falls_back_to_thread_key_without_ticket():
    """Direct/test calls with no ticket yet fall back to the email thread_key."""
    req = _req(messageId="msg-xyz")
    assert ConversationAgent._conv_key(req) == "email:msg-xyz"
