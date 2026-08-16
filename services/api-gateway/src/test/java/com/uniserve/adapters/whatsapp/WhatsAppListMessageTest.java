package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 29: interactive <b>list</b> messages.
 *
 * Reply-buttons (Feature 28) stop at three options, and Meta rejects the whole
 * send past that — so the four-option main menu and the citizen's ticket list
 * were simply unsendable. A list message carries up to ten rows, each with a
 * title and a second line of detail, which is also what finally gives a ticket
 * row room to name its complaint.
 *
 * The caller does not choose between the two shapes; {@link WhatsAppAdapter#needsList}
 * does, from the options themselves. Buttons stay the default because the
 * choices sit in the thread instead of behind a tap.
 */
class WhatsAppListMessageTest {

    private static List<Map<String, String>> options(String... titles) {
        List<Map<String, String>> out = new ArrayList<>();
        int i = 1;
        for (String title : titles) {
            Map<String, String> option = new LinkedHashMap<>();
            option.put("id", "menu_" + i++);
            option.put("title", title);
            out.add(option);
        }
        return out;
    }

    private static Map<String, String> row(String id, String title, String description) {
        Map<String, String> option = new LinkedHashMap<>();
        option.put("id", id);
        option.put("title", title);
        option.put("description", description);
        return option;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> interactiveOf(Map<String, Object> payload) {
        return (Map<String, Object>) payload.get("interactive");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> actionOf(Map<String, Object> payload) {
        return (Map<String, Object>) interactiveOf(payload).get("action");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rowsOf(Map<String, Object> payload) {
        List<Map<String, Object>> sections = (List<Map<String, Object>>) actionOf(payload).get("sections");
        assertEquals(1, sections.size(), "one section — an invented heading above the only group is clutter");
        return (List<Map<String, Object>>) sections.get(0).get("rows");
    }

    // ---- choosing the shape ---------------------------------------------

    @Test
    void aFourOptionMenuBecomesAListBecauseButtonsCapAtThree() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+919876543210", "Hi Ashok! What can I help with?", null,
                options("Update my details", "Ticket status", "New ticket", "End chat"),
                null, "Choose an option");

        assertEquals("interactive", payload.get("type"));
        assertEquals("list", interactiveOf(payload).get("type"));
        assertEquals("Choose an option", actionOf(payload).get("button"));

        List<Map<String, Object>> rows = rowsOf(payload);
        assertEquals(4, rows.size());
        assertEquals("menu_1", rows.get(0).get("id"));
        assertEquals("Update my details", rows.get(0).get("title"));
        assertFalse(rows.get(0).containsKey("description"), "no description was given, so no empty key");
    }

    @Test
    void threePlainOptionsAreStillReplyButtons() {
        // The Feature 28 rendering is the nicer one and must not regress: the
        // choices sit in the thread rather than behind a tap.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "Name or email?", null,
                options("Name", "Email", "Main menu"), null, "Choose");

        assertEquals("button", interactiveOf(payload).get("type"));
        assertTrue(actionOf(payload).containsKey("buttons"));
        assertFalse(actionOf(payload).containsKey("sections"));
    }

    @Test
    void aDescriptionForcesAListEvenWithinTheButtonLimit() {
        // A button has no second line. Rendering these as buttons would drop the
        // detail that tells one ticket from another, silently.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "Your tickets", null,
                List.of(row("TKT-00042", "TKT-00042 · Power cut", "In progress · reported 12 Aug")),
                null, null);

        assertEquals("list", interactiveOf(payload).get("type"));
        assertEquals("In progress · reported 12 Aug", rowsOf(payload).get(0).get("description"));
    }

    @Test
    void theListButtonLabelDefaultsRatherThanGoingOutEmpty() {
        // Meta rejects a list with no action button, and the label is optional
        // for the caller.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, options("A", "B", "C", "D"), null, "   ");

        assertEquals(WhatsAppAdapter.DEFAULT_LIST_BUTTON, actionOf(payload).get("button"));
    }

    // ---- limits Meta enforces by rejecting the whole send ----------------

    @Test
    void moreThanTenRowsAreDroppedRatherThanFailingTheSend() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null,
                options("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"), null, null);

        assertEquals(WhatsAppAdapter.MAX_ROWS, rowsOf(payload).size());
    }

    @Test
    void anOverlongRowTitleAndDescriptionAreClipped() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null,
                List.of(row("t1", "TKT-00042 · Water logging near the bus stand",
                        "d".repeat(200))),
                null, null);

        Map<String, Object> row = rowsOf(payload).get(0);
        assertEquals(WhatsAppAdapter.MAX_ROW_TITLE, row.get("title").toString().length());
        assertEquals(WhatsAppAdapter.MAX_ROW_DESCRIPTION, row.get("description").toString().length());
        assertTrue("TKT-00042 · Water logging near the bus stand".startsWith(row.get("title").toString()));
    }

    @Test
    void anOverlongListButtonLabelIsClipped() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, options("A", "B", "C", "D"), null,
                "Choose one of these options please");

        assertEquals(WhatsAppAdapter.MAX_LIST_BUTTON, actionOf(payload).get("button").toString().length());
    }

    @Test
    void duplicateRowIdsAreMadeUniqueBecauseMetaRejectsThem() {
        // Easy to hit by accident: ids default to the title, and two titles that
        // differ only past the 24-character clip arrive here identical.
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null,
                List.of(Map.of("title", "TKT-00042 · Power cut in Madambakkam"),
                        Map.of("title", "TKT-00042 · Power cut in Selaiyur"),
                        Map.of("title", "TKT-00043 · Water logging"),
                        Map.of("title", "Main menu")),
                null, null);

        List<Map<String, Object>> rows = rowsOf(payload);
        assertNotEquals(rows.get(0).get("id"), rows.get(1).get("id"));
        assertEquals(4, rows.stream().map(r -> r.get("id")).distinct().count());
    }

    @Test
    void anOverlongBodyAndFooterAreClippedOnAListToo() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "x".repeat(2000), null,
                options("A", "B", "C", "D"), "y".repeat(200), null);

        assertEquals(WhatsAppAdapter.MAX_BODY,
                ((Map<?, ?>) interactiveOf(payload).get("body")).get("text").toString().length());
        assertEquals(WhatsAppAdapter.MAX_FOOTER,
                ((Map<?, ?>) interactiveOf(payload).get("footer")).get("text").toString().length());
    }

    @Test
    void aRowWithNoTitleIsSkipped() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null, options("A", "  ", "C", "D"), null, null);

        assertEquals(3, rowsOf(payload).size(), "an unlabelled row is worse than one fewer");
    }

    @Test
    void rowsThatAllTurnOutBlankFallBackToTextWithTheQuotedContextIntact() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", "wamid.X", options(" ", "", "  ", ""), null, null);

        assertEquals("text", payload.get("type"));
        assertEquals(Map.of("body", "hi"), payload.get("text"));
        assertEquals(Map.of("message_id", "wamid.X"), payload.get("context"));
    }

    @Test
    void aMissingIdFallsBackToTheClippedTitleRatherThanSendingNull() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", null,
                List.of(Map.of("title", "Update my details"), Map.of("title", "Ticket status"),
                        Map.of("title", "New ticket"), Map.of("title", "End chat")),
                null, null);

        assertEquals("Update my details", rowsOf(payload).get(0).get("id"));
    }

    @Test
    void aQuotedReplyContextStillRidesAlongWithAList() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload(
                "+91987", "hi", "wamid.ABC", options("A", "B", "C", "D"), null, null);

        assertEquals(Map.of("message_id", "wamid.ABC"), payload.get("context"));
    }

    // ---- the inbound half --------------------------------------------------

    @Test
    void theParserReadsBackARowTheCitizenTapped() {
        // Already supported since Feature 02b, but until now nothing ever sent a
        // list, so this branch was unreachable. A tap arrives as the row TITLE,
        // which is what ai-core matches against the tenant's configured labels.
        String json = "{\"entry\":[{\"changes\":[{\"value\":{\"messages\":[{"
                + "\"from\":\"919876543210\",\"id\":\"wamid.IN\",\"timestamp\":\"1719475200\","
                + "\"type\":\"interactive\","
                + "\"interactive\":{\"type\":\"list_reply\","
                + "\"list_reply\":{\"id\":\"menu_2\",\"title\":\"Ticket status\","
                + "\"description\":\"See your open complaints\"}}"
                + "}]}}]}]}";

        List<com.uniserve.adapters.ChannelMessageReceived> events;
        try {
            events = WhatsAppParser.parse(new ObjectMapper().readTree(json), "t1");
        } catch (Exception e) {
            throw new AssertionError("the webhook body should parse", e);
        }

        assertEquals(1, events.size());
        assertEquals("Ticket status", events.get(0).rawText());
    }
}
