package com.uniserve.adapters.whatsapp;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Feature 24: reading Meta's wamid off a send response.
 *
 * WhatsApp is the channel that genuinely depends on this. It has no subject
 * line, so it has no durable ticket reference in each message — the one exact
 * routing signal it can offer is "which message did the citizen swipe-reply
 * to", and that is only usable if we recorded the id of the message we sent.
 * Without it, a reply of "Yes it is" has to be matched by heuristics, which is
 * how it ended up on the wrong ticket.
 */
class WhatsAppWamidTest {

    @Test
    void theWamidIsReadFromAGraphApiSendResponse() {
        String body = """
                {"messaging_product":"whatsapp",
                 "contacts":[{"input":"919000000000","wa_id":"919000000000"}],
                 "messages":[{"id":"wamid.HBgMOTE5MDAwMDAwMDAwFQIAERgS"}]}
                """;
        assertEquals("wamid.HBgMOTE5MDAwMDAwMDAwFQIAERgS", WhatsAppAdapter.extractWamid(body));
    }

    @Test
    void anUnexpectedSendResponseCostsTheShortcutNotTheReply() {
        // The message has ALREADY reached the citizen by the time this parses,
        // so every one of these must yield null rather than throw.
        assertNull(WhatsAppAdapter.extractWamid(null));
        assertNull(WhatsAppAdapter.extractWamid(""));
        assertNull(WhatsAppAdapter.extractWamid("not json"));
        assertNull(WhatsAppAdapter.extractWamid("{}"));
        assertNull(WhatsAppAdapter.extractWamid("{\"messages\":[]}"));
        assertNull(WhatsAppAdapter.extractWamid("{\"messages\":[{}]}"));
        assertNull(WhatsAppAdapter.extractWamid("{\"messages\":[{\"id\":\"\"}]}"));
    }
}
