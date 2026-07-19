"""Auto-generated email detection + reserved-domain send guard (TKT-00013).

A Gmail bounce (mailer-daemon DSN) once became a confirmed "technical
complaint": dev-seeded acks were emailed to fake @example.com addresses, Gmail
bounced them, IMAP ingested the bounce, and the assistant filed it. These
tests cover the ai-core layers of the fix (the EmailAdapter header-based
filter is the Java first line of defence).
"""

import asyncio

from app.events.dispatcher import is_auto_generated_email
from app.notifications.sender import send_email


def test_bounce_and_noreply_senders_are_flagged():
    assert is_auto_generated_email("mailer-daemon@googlemail.com", None)
    assert is_auto_generated_email("MAILER-DAEMON@example.net", "anything")
    assert is_auto_generated_email("postmaster@corp.com", None)
    assert is_auto_generated_email("forwarding-noreply@google.com", None)
    assert is_auto_generated_email("no-reply@service.in", None)
    assert is_auto_generated_email("donotreply@bank.com", None)


def test_auto_subjects_are_flagged_for_normal_senders():
    assert is_auto_generated_email("citizen@gmail.com", "Delivery Status Notification (Failure)")
    assert is_auto_generated_email("citizen@gmail.com", "Automatic reply: power cut")
    assert is_auto_generated_email("citizen@gmail.com", "Out of office till Monday")
    assert is_auto_generated_email("citizen@gmail.com", "Undeliverable: your message")


def test_real_citizens_and_complaints_pass_through():
    assert not is_auto_generated_email("nithin@gmail.com", "Meter not working")
    assert not is_auto_generated_email("replymenow@gmail.com", "Re: [Ticket TKT-00042] update?")
    assert not is_auto_generated_email("citizen@gmail.com", None)
    assert not is_auto_generated_email(None, None)


def test_send_email_skips_reserved_test_domains():
    for addr in ("anon@example.com", "x@example.org", "y@sub.test", "z@thing.invalid"):
        result = asyncio.run(send_email(addr, "s", "b"))
        assert result == {"delivered": False, "reason": "reserved test-domain recipient"}
