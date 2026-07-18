"""Unit tests for ai.reply.send delivery (Feature 06 x 14)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.notifications.sender import deliver_reply, send_ticket_ack_email


def _run(coro):
    return asyncio.run(coro)


def _mock_async_client(json_body: dict):
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


def test_deliver_reply_sends_email_for_email_channel():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "email",
        "channelIdentityValue": "citizen@example.com",
        "messageText": "Please share your email or reply anonymous.",
        "isIdentityRequest": True,
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(deliver_reply(payload, trace_id="trace-1"))

    assert result == {"delivered": True}
    client.post.assert_awaited_once()
    url, kwargs = client.post.await_args.args, client.post.await_args.kwargs
    assert url[0].endswith("/api/v1/internal/adapters/email/test-send")
    assert kwargs["json"]["to"] == "citizen@example.com"
    assert kwargs["headers"]["X-Trace-Id"] == "trace-1"


def test_deliver_reply_embeds_ticket_number_in_subject_and_adds_do_not_remove_note():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "email",
        "channelIdentityValue": "citizen@example.com",
        "messageText": "Please share your name and mobile number.",
        "isIdentityRequest": True,
        "ticketNumber": "TKT-00050",
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(deliver_reply(payload, trace_id="trace-ticket"))

    kwargs = client.post.await_args.kwargs
    assert "TKT-00050" in kwargs["json"]["subject"]
    assert "do not remove" in kwargs["json"]["body"].lower()


def test_deliver_reply_forwards_origin_message_id_for_thread_continuity():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "email",
        "channelIdentityValue": "citizen@example.com",
        "messageText": "Following up on your complaint.",
        "ticketNumber": "TKT-00051",
        "originMessageId": "orig-msg-id-123",
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(deliver_reply(payload, trace_id="trace-thread"))

    kwargs = client.post.await_args.kwargs
    assert kwargs["json"]["inReplyToMessageId"] == "orig-msg-id-123"


def test_deliver_reply_skips_whatsapp_no_outbound_send():
    payload = {
        "channel": "whatsapp",
        "channelIdentityValue": "+919876543210",
        "messageText": "Thanks, logged your complaint.",
    }
    result = _run(deliver_reply(payload, trace_id="trace-2"))
    assert result["delivered"] is False


def test_deliver_reply_reports_failure_without_raising_when_gateway_says_not_sent():
    ctx, _client = _mock_async_client({"sent": False})
    payload = {"channel": "email", "channelIdentityValue": "citizen@example.com", "messageText": "hi"}
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(deliver_reply(payload))
    assert result == {"delivered": False}


def test_send_ticket_ack_email_includes_ticket_number_in_subject_and_body():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(send_ticket_ack_email(
            channel="email", to_address="citizen@example.com", ticket_number="TKT-00042",
            category="billing", status="open", trace_id="trace-3",
        ))

    assert result == {"delivered": True}
    kwargs = client.post.await_args.kwargs
    assert "TKT-00042" in kwargs["json"]["subject"]
    assert "TKT-00042" in kwargs["json"]["body"]
    assert "billing" in kwargs["json"]["body"]


def test_send_ticket_ack_email_forwards_origin_message_id_for_thread_continuity():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(send_ticket_ack_email(
            channel="email", to_address="citizen@example.com", ticket_number="TKT-00042",
            origin_message_id="orig-msg-id-456",
        ))
    kwargs = client.post.await_args.kwargs
    assert kwargs["json"]["inReplyToMessageId"] == "orig-msg-id-456"


def test_send_ticket_ack_email_skips_non_email_channel():
    result = _run(send_ticket_ack_email(
        channel="whatsapp", to_address="+919876543210", ticket_number="TKT-00042",
    ))
    assert result["delivered"] is False


def test_send_ticket_ack_email_skips_when_no_ticket_number():
    result = _run(send_ticket_ack_email(channel="email", to_address="citizen@example.com", ticket_number=None))
    assert result == {"delivered": False, "reason": "no ticket number"}
