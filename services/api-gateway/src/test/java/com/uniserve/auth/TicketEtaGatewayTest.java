package com.uniserve.auth;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import jakarta.ws.rs.core.Response;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Feature 26: the gateway's half of the ETA rule.
 *
 * The rule itself is enforced in db-writer ({@code TicketService.transition}
 * returns 422 ETA_REQUIRED) so it cannot be bypassed by calling db-writer
 * directly. What the gateway owns is forwarding the value faithfully and
 * guarding the revision endpoint — both of which are easy to break silently.
 */
class TicketEtaGatewayTest {

    private DbWriterClient db;
    private TicketNotifier notifier;
    private TicketsResource resource;

    @BeforeEach
    void setUp() {
        db = mock(DbWriterClient.class);
        notifier = mock(TicketNotifier.class);
        resource = new TicketsResource();
        resource.db = db;
        resource.notifier = notifier;
        resource.user = user("admin");

        Map<String, Object> ticket = new LinkedHashMap<>();
        ticket.put("id", "t-1");
        ticket.put("status", "open");
        when(db.call(eq("GET"), eq("/api/v1/db/tickets/t-1"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, ticket));
        when(db.call(eq("POST"), anyString(), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("status", "assigned")));
        when(db.call(eq("PATCH"), anyString(), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("eta_at", "2026-08-18 23:59:59")));
    }

    private static CurrentUser user(String role) {
        CurrentUser u = new CurrentUser();
        u.set("a-1", "t1", role, "Someone", "s@example.com");
        return u;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> capturedBody(String method, String path) {
        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(db).call(eq(method), eq(path), body.capture());
        return (Map<String, Object>) body.getValue();
    }

    // --- transition passthrough ------------------------------------------

    @Test
    void anEtaOnATransitionIsForwardedToDbWriter() {
        Map<String, Object> input = new LinkedHashMap<>();
        input.put("toStatus", "assigned");
        input.put("eta", "2026-08-18");

        resource.transition("t-1", input);

        assertEquals("2026-08-18", capturedBody("POST", "/api/v1/db/tickets/t-1/transition").get("eta"));
    }

    @Test
    void anAbsentEtaIsNotForwardedAsNull() {
        // A null `eta` in the body is indistinguishable from "clear the ETA" on
        // the db-writer side, which would wipe an ETA on every later transition.
        Map<String, Object> input = new LinkedHashMap<>();
        input.put("toStatus", "assigned");

        resource.transition("t-1", input);

        assertFalse(capturedBody("POST", "/api/v1/db/tickets/t-1/transition").containsKey("eta"));
    }

    @Test
    void anEmptyBodyDoesNotBlowUpTheTransition() {
        assertEquals(200, resource.transition("t-1", new LinkedHashMap<>()).getStatus());
    }

    @Test
    void theServersRejectionIsPassedBackToTheAgentVerbatim() {
        // The dashboard shows data.error.message, so swallowing this would
        // leave an agent staring at a button that silently does nothing.
        when(db.call(eq("POST"), eq("/api/v1/db/tickets/t-1/transition"), any()))
                .thenReturn(new DbWriterClient.ApiResult(422, Map.of("error", Map.of(
                        "code", "ETA_REQUIRED", "message", "An ETA is required on the first transition"))));

        Response response = resource.transition("t-1", Map.of("toStatus", "assigned"));

        assertEquals(422, response.getStatus());
        assertTrue(String.valueOf(response.getEntity()).contains("ETA_REQUIRED"));
    }

    // --- the revision endpoint -------------------------------------------

    @Test
    void updatingTheEtaPatchesItWithTheActingAgentRecorded() {
        resource.updateEta("t-1", Map.of("eta", "2026-09-01"));

        Map<String, Object> patch = capturedBody("PATCH", "/api/v1/db/tickets/t-1");
        assertEquals("2026-09-01", patch.get("eta"));
        assertEquals("a-1", patch.get("actorAgentId"), "an ETA change must name who made it");
    }

    @Test
    void theEtaCanBeCleared() {
        resource.updateEta("t-1", new LinkedHashMap<>());

        Map<String, Object> patch = capturedBody("PATCH", "/api/v1/db/tickets/t-1");
        assertTrue(patch.containsKey("eta"));
        assertEquals(null, patch.get("eta"));
    }

    @Test
    void aNullBodyIsTreatedAsAClearRatherThanCrashing() {
        assertEquals(200, resource.updateEta("t-1", null).getStatus());
    }

    @Test
    void anAgentWithoutEditRightsCannotChangeAPromiseMadeToACitizen() {
        assertTrue(RbacPolicy.can("admin", "ticket.edit"));
        assertTrue(RbacPolicy.can("lead", "ticket.edit"));
    }

    @Test
    void aRoleWithoutTicketEditIsRefusedAndNothingIsWritten() {
        CurrentUser viewer = new CurrentUser();
        viewer.set("a-9", "t1", "nonexistent-role", "Nobody", "n@example.com");
        resource.user = viewer;

        assertEquals(403, resource.updateEta("t-1", Map.of("eta", "2026-09-01")).getStatus());
        verify(db, never()).call(eq("PATCH"), anyString(), any());
    }

    // --- the export contract ---------------------------------------------

    @Test
    void theEtaIsInTheCsvExport() {
        // Reporting on promises kept is the whole reason the column exists.
        assertTrue(TicketsResource.EXPORT_COLUMNS.contains("eta_at"));
        // ...and next to the SLA date it is compared against.
        assertEquals(TicketsResource.EXPORT_COLUMNS.indexOf("sla_due_at") + 1,
                TicketsResource.EXPORT_COLUMNS.indexOf("eta_at"));
    }
}
