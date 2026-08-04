package com.uniserve.auth;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 21/23: admin-only Cancel and the CSV export. Pure-function tests —
 * the RBAC policy and the CSV writer are both static and need no container.
 */
class TicketExportAndCancelTest {

    // --- Cancel is admin-only -------------------------------------------

    @Test
    void cancelIsTheOneStatusActionALeadCannotPerform() {
        assertTrue(RbacPolicy.can("admin", "ticket.status.to_cancelled"));
        // A lead can close and even reopen, but cancelling declares the ticket
        // was never real work — deliberately narrower than everything else.
        assertFalse(RbacPolicy.can("lead", "ticket.status.to_cancelled"));
        assertFalse(RbacPolicy.can("agent", "ticket.status.to_cancelled"));
        assertTrue(RbacPolicy.can("lead", "ticket.status.resolved_to_closed"));
    }

    @Test
    void cancelledMapsToItsOwnPermissionNotTheGenericEditFallback() {
        assertEquals("ticket.status.to_cancelled", TicketsResource.transitionAction("cancelled"));
        // Guard against a typo silently falling through to "ticket.edit",
        // which a lead HAS — that would hand leads the cancel button.
        assertEquals("ticket.edit", TicketsResource.transitionAction("nonsense"));
    }

    // --- Export permission ----------------------------------------------

    @Test
    void exportIsAdminAndLeadOnly() {
        assertTrue(RbacPolicy.can("admin", "ticket.export"));
        assertTrue(RbacPolicy.can("lead", "ticket.export"));
        assertFalse(RbacPolicy.can("agent", "ticket.export"));
    }

    // --- CSV writing -----------------------------------------------------

    @Test
    void csvCellQuotesCommasQuotesAndNewlines() {
        assertEquals("plain", TicketsResource.csvCell("plain"));
        assertEquals("\"a,b\"", TicketsResource.csvCell("a,b"));
        assertEquals("\"say \"\"hi\"\"\"", TicketsResource.csvCell("say \"hi\""));
        assertEquals("\"line1\nline2\"", TicketsResource.csvCell("line1\nline2"));
        assertEquals("", TicketsResource.csvCell(null));
    }

    @Test
    void csvCellNeutralisesFormulaInjection() {
        // These cells hold text a CITIZEN controls (their name, a complaint
        // resolution). Without the leading quote, Excel/Sheets executes them.
        assertEquals("'=1+1", TicketsResource.csvCell("=1+1"));
        assertEquals("'+CMD", TicketsResource.csvCell("+CMD"));
        assertEquals("'-2", TicketsResource.csvCell("-2"));
        assertEquals("'@SUM(A1)", TicketsResource.csvCell("@SUM(A1)"));
        // A formula that ALSO contains a comma must still be quoted as a field.
        assertEquals("\"'=HYPERLINK(\"\"x\"\",\"\"y\"\")\"",
                TicketsResource.csvCell("=HYPERLINK(\"x\",\"y\")"));
    }

    @Test
    void csvRowResolvesTheAssigneeNameAndKeepsColumnOrder() {
        Map<String, Object> ticket = new LinkedHashMap<>();
        ticket.put("ticket_number", "TKT-00042");
        ticket.put("status", "open");
        ticket.put("citizen_name", "Nithya, R.");
        ticket.put("assigned_to", "agent-1");

        String row = TicketsResource.csvRow(ticket, Map.of("agent-1", "Priya"), TicketsResource.EXPORT_COLUMNS);

        assertTrue(row.startsWith("TKT-00042,open,"), row);
        assertTrue(row.contains("\"Nithya, R.\""), row);
        assertTrue(row.contains("Priya"), row);
        // Absent columns become empty fields rather than "null" text.
        assertFalse(row.contains("null"), row);
    }

    // --- Feature 23: full-detail export ---------------------------------

    @Test
    void fullExportCarriesEveryTicketDetailFieldAndAllThreeTimelines() {
        List<String> full = TicketsResource.fullColumns();

        // The summary shape is a strict PREFIX of the full one, so a consumer
        // reading by column index is not broken by the extra columns.
        assertEquals(TicketsResource.EXPORT_COLUMNS, full.subList(0, TicketsResource.EXPORT_COLUMNS.size()));
        // The complaint itself, the citizen, and each timeline the ticket-detail
        // page shows — the fields whose absence made the old export unusable.
        for (String required : List.of("chief_complaint", "citizen_name", "citizen_email", "citizen_phone",
                "resolution", "conversation", "internal_notes", "audit_trail")) {
            assertTrue(full.contains(required), "full export is missing " + required);
        }
        // Wide transcript cells sort last so the scalar columns are all visible
        // before a spreadsheet needs horizontal scrolling.
        assertEquals("audit_trail", full.get(full.size() - 1));
    }

    @Test
    void fullRowEmbedsTranscriptsAsQuotedMultiLineCells() {
        Map<String, Object> ticket = new LinkedHashMap<>();
        ticket.put("ticket_number", "TKT-00042");
        ticket.put("status", "resolved");
        ticket.put("chief_complaint", "No power in Anna Nagar since Tuesday");
        ticket.put("conversation", "[t1] Received · citizen: No power\n[t2] Sent · ai: We are on it");

        String row = TicketsResource.csvRow(ticket, Map.of(), TicketsResource.fullColumns());

        assertTrue(row.contains("No power in Anna Nagar since Tuesday"), row);
        // Embedded newlines must be inside a quoted field, or the CSV gains a row.
        assertTrue(row.contains("\"[t1] Received · citizen: No power\n[t2] Sent · ai: We are on it\""), row);
    }

    @Test
    void transcriptEntriesAreOneLineEachRegardlessOfTheOriginalText() {
        StringBuilder out = new StringBuilder();
        TicketsResource.appendEntry(out, "2026-08-04 09:12", "Received · citizen",
                "No power.\r\n\r\nSince Tuesday.\n  Whole street.");
        TicketsResource.appendEntry(out, "2026-08-04 09:13", "Sent · ai", "Logged as TKT-00042");

        // A multi-line email body folds into ONE entry line, so the cell's own
        // newlines only ever mean "next entry".
        assertEquals(
                "[2026-08-04 09:12] Received · citizen: No power. Since Tuesday. Whole street.\n"
                        + "[2026-08-04 09:13] Sent · ai: Logged as TKT-00042",
                out.toString());
    }

    @Test
    void transcriptIsCutOnAnEntryBoundaryWithAVisibleMarker() {
        // Excel silently drops anything past 32,767 characters in a cell, so a
        // long thread must be cut here and SAY it was cut.
        StringBuilder out = new StringBuilder();
        String entry = "[2026-08-04 09:12] Received · citizen: " + "x".repeat(200);
        while (out.length() <= 31_000) {
            out.append(out.length() == 0 ? "" : "\n").append(entry);
        }

        String cut = TicketsResource.truncateTranscript(out.toString(), "messages");

        assertTrue(cut.endsWith("[… truncated: this ticket has more messages than fit one cell]"), cut);
        // Cut on a line boundary: the last kept entry is whole.
        String lastKept = cut.substring(0, cut.lastIndexOf('\n'));
        assertTrue(lastKept.endsWith(entry), "transcript was cut mid-entry");
    }

    @Test
    void anUnreadableTimelineIsIsolatedToItsOwnCellAndSaysSo() {
        // db-writer throws on any 4xx/5xx, so without isolation one unreadable
        // ticket would abort a 2,000-row export and lose 1,999 good rows. A
        // blank cell would be worse than a marker: it reads as "no notes".
        TicketsResource resource = new TicketsResource();

        String ok = resource.timeline("t-1", "notes", () -> "[t1] Priya: looked into it");
        String failed = resource.timeline("t-1", "notes", () -> {
            throw new IllegalStateException("db-writer GET ... -> 500");
        });

        assertEquals("[t1] Priya: looked into it", ok);
        assertEquals("[unavailable: this ticket's notes could not be read at export time]", failed);
    }

    @Test
    void shortTranscriptIsLeftExactlyAsItIs() {
        assertEquals("[t1] a: b", TicketsResource.truncateTranscript("[t1] a: b", "messages"));
        assertEquals("", TicketsResource.truncateTranscript("", "notes"));
    }
}
