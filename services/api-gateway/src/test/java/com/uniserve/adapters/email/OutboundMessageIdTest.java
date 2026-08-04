package com.uniserve.adapters.email;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 24: we mint our own outbound {@code Message-ID}.
 *
 * Generating it is the only way to KNOW it — Resend's response {@code id} is an
 * internal handle rather than the RFC 5322 header, and an SMTP send returns
 * nothing at all. A citizen's reply quotes this value back in
 * {@code In-Reply-To}, which is how routing identifies the ticket they are
 * replying on.
 */
class OutboundMessageIdTest {

    @Test
    void everyOutboundEmailGetsItsOwnMessageId() {
        String first = EmailAdapter.newMessageId();
        String second = EmailAdapter.newMessageId();
        assertNotEquals(first, second);
        // Stored WITHOUT angle brackets, matching how inbound Message-IDs are
        // parsed (`extractMessageId` strips them) — an id that round-tripped as
        // <x@y> outbound and x@y inbound would never match itself.
        assertFalse(first.startsWith("<"), first);
        assertFalse(first.endsWith(">"), first);
        assertTrue(first.contains("@"), first);
    }

    @Test
    void resendHeadersCarryOurMessageIdBracketedForTheWire() {
        Map<String, String> headers = ResendEmailClient.buildHeaders(
                "uniserve-abc@uniserve.local", "uniserve-def@uniserve.local");

        // RFC 5322 requires the brackets on the wire even though we store the
        // bare id, so the bracketing lives in exactly one place.
        assertEquals("<uniserve-def@uniserve.local>", headers.get("Message-ID"));
        assertEquals("<uniserve-abc@uniserve.local>", headers.get("In-Reply-To"));
        assertEquals("<uniserve-abc@uniserve.local>", headers.get("References"));
    }

    @Test
    void resendHeadersOmitThreadingWhenThereIsNothingToThreadTo() {
        Map<String, String> headers = ResendEmailClient.buildHeaders(null, "uniserve-def@uniserve.local");
        assertEquals("<uniserve-def@uniserve.local>", headers.get("Message-ID"));
        assertFalse(headers.containsKey("In-Reply-To"));
        assertFalse(headers.containsKey("References"));
    }

    @Test
    void alreadyBracketedIdsAreNotDoubleBracketed() {
        Map<String, String> headers = ResendEmailClient.buildHeaders("<a@b>", "<c@d>");
        assertEquals("<c@d>", headers.get("Message-ID"));
        assertEquals("<a@b>", headers.get("In-Reply-To"));
    }
}
