package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 28: the outbound half of interactive reply buttons.
 *
 * The inbound half has worked since Feature 02b — {@link WhatsAppParser} already
 * reads {@code button_reply.title}. What was missing was ever SENDING a message
 * with buttons on it, so the parser's interactive branch was unreachable in
 * practice.
 *
 * Meta rejects the whole send if any limit is exceeded, which means the citizen
 * receives nothing at all. Every cap is therefore enforced by truncation here
 * rather than trusted from the caller.
 */
class WhatsAppInteractiveTest {

    private static List<Map<String, String>> buttons(String... titles) {
        List<Map<String, String>> out = new ArrayList<>();
        int i = 1;
        for (String title : titles) {
            Map<String, String> b = new LinkedHashMap<>();
            b.put("id", "menu_" + i++);
            b.put("title", title);
            out.add(b);
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> interactiveOf(Map<String, Object> payload) {
        return (Map<String, Object>) payload.get("interactive");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> repliesOf(Map<String, Object> payload) {
        Map<String, Object> action = (Map<String, Object>) interactiveOf(payload).get("action");
        return (List<Map<String, Object>>) action.get("buttons");
    }

    @SuppressWarnings("unchecked")
    private static String titleOf(Map<String, Object> button) {
        return (String) ((Map<String, Object>) button.get("reply")).get("title");
    }

    // ---- shape ----------------------------------------------------------

    @Test
    void buttonsProduceMetasInteractiveShape() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+919876543210", "Welcome to TNEB!", null,
                buttons("Ticket status", "New ticket", "End chat"), "Press # for the menu");

        assertEquals("whatsapp", payload.get("messaging_product"));
        assertEquals("919876543210", payload.get("to"));
        assertEquals("interactive", payload.get("type"));
        assertFalse(payload.containsKey("text"), "an interactive message carries no top-level text");

        Map<String, Object> interactive = interactiveOf(payload);
        assertEquals("button", interactive.get("type"));
        assertEquals(Map.of("text", "Welcome to TNEB!"), interactive.get("body"));
        assertEquals(Map.of("text", "Press # for the menu"), interactive.get("footer"));

        List<Map<String, Object>> replies = repliesOf(payload);
        assertEquals(3, replies.size());
        assertEquals("reply", replies.get(0).get("type"));
        assertEquals(Map.of("id", "menu_1", "title", "Ticket status"), replies.get(0).get("reply"));
    }

    @Test
    void noButtonsStillSendsPlainTextExactlyAsBefore() {
        // Every pre-Feature-28 caller passes through this path unchanged.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload("+91987", "hello", null);

        assertEquals("text", payload.get("type"));
        assertEquals(Map.of("body", "hello"), payload.get("text"));
        assertFalse(payload.containsKey("interactive"));
    }

    @Test
    void anEmptyButtonListIsTreatedAsPlainText() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hello", null, List.of(), null);
        assertEquals("text", payload.get("type"));
    }

    @Test
    void aQuotedReplyContextStillRidesAlongWithButtons() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", "wamid.ABC", buttons("One"), null);

        assertEquals(Map.of("message_id", "wamid.ABC"), payload.get("context"));
    }

    @Test
    void noFooterMeansNoFooterKeyRatherThanAnEmptyOne() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, buttons("One"), "   ");

        assertFalse(interactiveOf(payload).containsKey("footer"));
    }

    // ---- limits Meta enforces by rejecting the whole send ----------------

    @Test
    void moreThanThreeOptionsBecomeAListRatherThanLosingTheSurplus() {
        // Feature 28 clipped to three, so options four and five never reached
        // the citizen at all — survivable when the menu had exactly three, not
        // once it had four. Feature 29 sends them as a list instead; the
        // three-button cap now decides the SHAPE rather than truncating.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, buttons("A", "B", "C", "D", "E"), null);

        assertEquals("list", interactiveOf(payload).get("type"));
        assertTrue(WhatsAppAdapter.needsList(buttons("A", "B", "C", "D", "E")));
        assertFalse(interactiveOf(payload).toString().contains("\"buttons\""));
    }

    @Test
    void exactlyThreeOptionsStayButtons() {
        // The boundary the shape choice turns on.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, buttons("A", "B", "C"), null);

        assertEquals("button", interactiveOf(payload).get("type"));
        assertEquals(WhatsAppAdapter.MAX_BUTTONS, repliesOf(payload).size());
    }

    @Test
    void anOverlongTitleIsClippedRatherThanFailingTheSend() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null,
                buttons("Check the status of an existing ticket"), null);

        String title = titleOf(repliesOf(payload).get(0));
        assertEquals(WhatsAppAdapter.MAX_BUTTON_TITLE, title.length());
        assertTrue("Check the status of an existing ticket".startsWith(title));
    }

    @Test
    void anOverlongBodyAndFooterAreClipped() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "x".repeat(2000), null, buttons("One"), "y".repeat(200));

        assertEquals(WhatsAppAdapter.MAX_BODY,
                ((Map<?, ?>) interactiveOf(payload).get("body")).get("text").toString().length());
        assertEquals(WhatsAppAdapter.MAX_FOOTER,
                ((Map<?, ?>) interactiveOf(payload).get("footer")).get("text").toString().length());
    }

    @Test
    void aButtonWithNoTitleIsSkipped() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, buttons("Real", "   "), null);

        assertEquals(1, repliesOf(payload).size(), "an unlabelled button is worse than one fewer");
    }

    @Test
    void buttonsThatAllTurnOutBlankFallBackToText() {
        // Meta rejects a button message with no buttons, so this must not be
        // sent as interactive at all.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", "wamid.X", buttons("  ", ""), null);

        assertEquals("text", payload.get("type"));
        assertEquals(Map.of("body", "hi"), payload.get("text"));
        assertEquals(Map.of("message_id", "wamid.X"), payload.get("context"));
    }

    @Test
    void aMissingIdFallsBackToTheTitleRatherThanSendingNull() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, List.of(Map.of("title", "End chat")), null);

        @SuppressWarnings("unchecked")
        Map<String, Object> reply = (Map<String, Object>) repliesOf(payload).get(0).get("reply");
        assertEquals("End chat", reply.get("id"));
    }

    // ---- the inbound half this finally makes reachable -------------------

    @Test
    void theParserReadsBackWhatWeSend() throws Exception {
        // A tap comes back as the button's TITLE, which is why ai-core matches
        // taps against the tenant's configured labels rather than a word list.
        String json = "{\"entry\":[{\"changes\":[{\"value\":{\"messages\":[{"
                + "\"from\":\"919876543210\",\"id\":\"wamid.IN\",\"timestamp\":\"1719475200\","
                + "\"type\":\"interactive\","
                + "\"interactive\":{\"type\":\"button_reply\","
                + "\"button_reply\":{\"id\":\"menu_2\",\"title\":\"New ticket\"}}"
                + "}]}}]}]}";

        var events = WhatsAppParser.parse(new ObjectMapper().readTree(json), "t1");

        assertEquals(1, events.size());
        assertEquals("New ticket", events.get(0).rawText());
    }
}
