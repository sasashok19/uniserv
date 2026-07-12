package com.uniserve.adapters.email;

import com.uniserve.adapters.ChannelMessageReceived;
import jakarta.mail.Session;
import jakarta.mail.internet.MimeMessage;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for email MIME parsing (Feature 02a) — no IMAP server required. */
class EmailAdapterParseTest {

    private static MimeMessage mime(String raw) throws Exception {
        Session session = Session.getInstance(new Properties());
        return new MimeMessage(session, new ByteArrayInputStream(raw.getBytes(StandardCharsets.UTF_8)));
    }

    @Test
    void extractsFromAddressAsUnverifiedEmailIdentity() throws Exception {
        MimeMessage msg = mime("""
                From: John <john@example.com>
                Subject: Billing
                Message-ID: <m1@example.com>
                Content-Type: text/plain; charset=UTF-8

                My bill is wrong""");

        ChannelMessageReceived event = EmailAdapter.parseMessage(msg, "default");

        assertEquals("email", event.channelIdentity().type());
        assertEquals("john@example.com", event.channelIdentity().value());
        assertFalse(event.channelIdentity().verified(), "email identity is never natively verified");
        assertEquals("My bill is wrong", event.rawText());
    }

    @Test
    void stripsHtmlToPlainText() throws Exception {
        MimeMessage msg = mime("""
                From: jane@example.com
                Subject: HTML
                Content-Type: text/html; charset=UTF-8

                <html><body><p>Hello <b>world</b></p><p>My&nbsp;bill is wrong</p></body></html>""");

        ChannelMessageReceived event = EmailAdapter.parseMessage(msg, "default");

        String text = event.rawText();
        assertFalse(text.contains("<"), "tags should be stripped: " + text);
        assertTrue(text.contains("Hello world"), text);
        assertTrue(text.contains("My bill is wrong"), text);
    }

    @Test
    void replyEmailThreadIdMatchesParentMessageId() throws Exception {
        MimeMessage msg = mime("""
                From: john@example.com
                Subject: Re: Billing
                Message-ID: <reply-2@example.com>
                In-Reply-To: <parent-1@example.com>
                References: <parent-1@example.com>
                Content-Type: text/plain; charset=UTF-8

                Following up""");

        ChannelMessageReceived event = EmailAdapter.parseMessage(msg, "default");

        assertEquals("parent-1@example.com", event.threadId());
        assertEquals("parent-1@example.com", event.inReplyTo());
    }

    @Test
    void newEmailWithoutThreadingHeadersHasNullThreadId() throws Exception {
        MimeMessage msg = mime("""
                From: new@example.com
                Subject: New
                Message-ID: <new-1@example.com>
                Content-Type: text/plain; charset=UTF-8

                Brand new conversation""");

        ChannelMessageReceived event = EmailAdapter.parseMessage(msg, "default");
        assertEquals(null, event.threadId());
    }
}
