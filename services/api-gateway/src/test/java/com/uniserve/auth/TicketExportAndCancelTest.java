package com.uniserve.auth;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 21: admin-only Cancel and the CSV export. Pure-function tests — the
 * RBAC policy and the CSV writer are both static and need no container.
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

        String row = TicketsResource.csvRow(ticket, Map.of("agent-1", "Priya"));

        assertTrue(row.startsWith("TKT-00042,open,"), row);
        assertTrue(row.contains("\"Nithya, R.\""), row);
        assertTrue(row.contains("Priya"), row);
        // Absent columns become empty fields rather than "null" text.
        assertFalse(row.contains("null"), row);
    }
}
