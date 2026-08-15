"""Unit tests for ai.reply.send delivery (Feature 06 x 14)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.notifications.sender import _error_body_snippet, deliver_reply, send_email, send_ticket_ack, send_whatsapp


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
        "channelIdentityValue": "citizen@citizen-mail.dev",
        "messageText": "Please share your email or reply anonymous.",
        "isIdentityRequest": True,
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(deliver_reply(payload, trace_id="trace-1"))

    assert result["delivered"] is True
    client.post.assert_awaited_once()
    url, kwargs = client.post.await_args.args, client.post.await_args.kwargs
    assert url[0].endswith("/api/v1/internal/adapters/email/test-send")
    assert kwargs["json"]["to"] == "citizen@citizen-mail.dev"
    assert kwargs["headers"]["X-Trace-Id"] == "trace-1"


def test_deliver_reply_embeds_ticket_number_in_subject_and_adds_do_not_remove_note():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "email",
        "channelIdentityValue": "citizen@citizen-mail.dev",
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
        "channelIdentityValue": "citizen@citizen-mail.dev",
        "messageText": "Following up on your complaint.",
        "ticketNumber": "TKT-00051",
        "originMessageId": "orig-msg-id-123",
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(deliver_reply(payload, trace_id="trace-thread"))

    kwargs = client.post.await_args.kwargs
    assert kwargs["json"]["inReplyToMessageId"] == "orig-msg-id-123"


def test_deliver_reply_sends_whatsapp_for_whatsapp_channel():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "whatsapp",
        "channelIdentityValue": "+919876543210",
        "messageText": "Thanks, logged your complaint.",
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(deliver_reply(payload, trace_id="trace-2"))

    assert result["delivered"] is True
    client.post.assert_awaited_once()
    url, kwargs = client.post.await_args.args, client.post.await_args.kwargs
    assert url[0].endswith("/api/v1/internal/adapters/whatsapp/send")
    assert kwargs["json"]["to"] == "+919876543210"
    assert kwargs["json"]["body"] == "Thanks, logged your complaint."
    assert kwargs["headers"]["X-Trace-Id"] == "trace-2"


def test_deliver_reply_whatsapp_forwards_origin_message_id_as_context_and_skips_subject_note():
    ctx, client = _mock_async_client({"sent": True})
    payload = {
        "channel": "whatsapp",
        "channelIdentityValue": "+919876543210",
        "messageText": "Following up on your complaint.",
        "ticketNumber": "TKT-00051",
        "originMessageId": "wamid.orig001",
    }
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(deliver_reply(payload, trace_id="trace-thread-wa"))

    kwargs = client.post.await_args.kwargs
    assert kwargs["json"]["contextMessageId"] == "wamid.orig001"
    # WhatsApp has no subject line, so the "don't remove the ticket number
    # from the subject" note (which is email-specific) must not appear.
    assert "do not remove" not in kwargs["json"]["body"].lower()


def test_deliver_reply_reports_unknown_channel_as_undelivered():
    payload = {
        "channel": "ivr",
        "channelIdentityValue": "+919876543210",
        "messageText": "Thanks, logged your complaint.",
    }
    result = _run(deliver_reply(payload, trace_id="trace-2b"))
    assert result["delivered"] is False


def test_send_whatsapp_posts_to_whatsapp_send_endpoint():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(send_whatsapp("+919876543210", "hello", trace_id="trace-wa-direct"))

    assert result["delivered"] is True
    kwargs = client.post.await_args.kwargs
    assert kwargs["json"] == {"to": "+919876543210", "buttons": None, "footer": None, "body": "hello", "contextMessageId": None}


def test_send_whatsapp_reports_failure_without_raising_when_gateway_says_not_sent():
    ctx, _client = _mock_async_client({"sent": False})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(send_whatsapp("+919876543210", "hello"))
    assert result["delivered"] is False


def test_deliver_reply_reports_failure_without_raising_when_gateway_says_not_sent():
    ctx, _client = _mock_async_client({"sent": False})
    payload = {"channel": "email", "channelIdentityValue": "citizen@citizen-mail.dev", "messageText": "hi"}
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(deliver_reply(payload))
    assert result["delivered"] is False


# ---------------------------------------------------------------------------
# Cross-service debuggability fix: api-gateway's real error detail (e.g.
# Resend's 403 "you can only send to your own verified address") previously
# only ever appeared in api-gateway's OWN logs — httpx's default exception
# message doesn't include the response body, so ai-core's log line said
# nothing more than "Server error '500...'", forcing a cross-service log
# hunt for every delivery failure.
# ---------------------------------------------------------------------------

def test_error_body_snippet_extracts_response_text_from_http_status_error():
    request = httpx.Request("POST", "https://example.test/test-send")
    response = httpx.Response(403, text='{"message":"Resend 403 detail"}', request=request)
    exc = httpx.HTTPStatusError("error", request=request, response=response)
    assert _error_body_snippet(exc) == '{"message":"Resend 403 detail"}'


def test_error_body_snippet_returns_none_for_non_http_exceptions():
    assert _error_body_snippet(ValueError("boom")) is None


def test_send_email_logs_the_real_error_body_on_http_failure(caplog):
    request = httpx.Request("POST", "https://example.test/test-send")
    response = httpx.Response(403, text='{"message":"Resend 403 detail"}', request=request)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx), \
         pytest.raises(httpx.HTTPStatusError):
        _run(send_email("citizen@citizen-mail.dev", "Subject", "Body"))

    assert "Resend 403 detail" in caplog.text


def test_send_whatsapp_logs_the_real_error_body_on_http_failure(caplog):
    request = httpx.Request("POST", "https://example.test/send")
    response = httpx.Response(500, text="upstream WhatsApp error detail", request=request)
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx), \
         pytest.raises(httpx.HTTPStatusError):
        _run(send_whatsapp("+919876543210", "hello"))

    assert "upstream WhatsApp error detail" in caplog.text


def test_send_ticket_ack_includes_ticket_number_in_subject_and_body_for_email():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(send_ticket_ack(
            channel="email", to_address="citizen@citizen-mail.dev", ticket_number="TKT-00042",
            category="billing", status="open", trace_id="trace-3",
        ))

    assert result["delivered"] is True
    kwargs = client.post.await_args.kwargs
    assert "TKT-00042" in kwargs["json"]["subject"]
    assert "TKT-00042" in kwargs["json"]["body"]
    assert "billing" in kwargs["json"]["body"]


def test_send_ticket_ack_forwards_origin_message_id_for_thread_continuity():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        _run(send_ticket_ack(
            channel="email", to_address="citizen@citizen-mail.dev", ticket_number="TKT-00042",
            origin_message_id="orig-msg-id-456",
        ))
    kwargs = client.post.await_args.kwargs
    assert kwargs["json"]["inReplyToMessageId"] == "orig-msg-id-456"


def test_send_ticket_ack_sends_whatsapp_without_email_subject_note():
    ctx, client = _mock_async_client({"sent": True})
    with patch("app.notifications.sender.httpx.AsyncClient", return_value=ctx):
        result = _run(send_ticket_ack(
            channel="whatsapp", to_address="+919876543210", ticket_number="TKT-00042",
            category="billing", origin_message_id="wamid.orig042",
        ))

    assert result["delivered"] is True
    url, kwargs = client.post.await_args.args, client.post.await_args.kwargs
    assert url[0].endswith("/api/v1/internal/adapters/whatsapp/send")
    assert kwargs["json"]["to"] == "+919876543210"
    assert "TKT-00042" in kwargs["json"]["body"]
    assert "billing" in kwargs["json"]["body"]
    assert kwargs["json"]["contextMessageId"] == "wamid.orig042"
    assert "do not remove" not in kwargs["json"]["body"].lower()


def test_send_ticket_ack_skips_unknown_channel():
    result = _run(send_ticket_ack(
        channel="ivr", to_address="+919876543210", ticket_number="TKT-00042",
    ))
    assert result["delivered"] is False


def test_send_ticket_ack_skips_when_no_ticket_number():
    result = _run(send_ticket_ack(channel="email", to_address="citizen@citizen-mail.dev", ticket_number=None))
    assert result == {"delivered": False, "reason": "no ticket number"}
