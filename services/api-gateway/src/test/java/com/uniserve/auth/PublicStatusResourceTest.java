package com.uniserve.auth;

import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Unit tests for {@link PublicStatusResource} (Feature 12 x 18b). */
class PublicStatusResourceTest {

    private DbWriterClient db;
    private PublicStatusResource resource;

    @BeforeEach
    void setUp() {
        db = mock(DbWriterClient.class);
        resource = new PublicStatusResource();
        resource.db = db;
        resource.defaultTenant = "t1";
    }

    @Test
    void ticketNumberLookupExpandsToAllOfTheSameIdentitysTickets() {
        // The exact reported bug: TKT-00013 exists but has no direct lookup
        // path -- previously always fell through to the anon-ref branch,
        // which can never match a ticket number, and 404'd despite the
        // ticket existing.
        when(db.listTickets("ticketNumber=TKT-00013")).thenReturn(List.of(Map.of(
                "id", "tkt-id-13", "ticket_number", "TKT-00013", "tenant_id", "t1",
                "identity_id", "m-1", "status", "open", "category", "outage")));
        when(db.listTickets("tenantId=t1&identityId=m-1")).thenReturn(List.of(
                Map.of("ticket_number", "TKT-00013", "status", "open", "category", "outage", "updated_at", "2026-08-01"),
                Map.of("ticket_number", "TKT-00009", "status", "resolved", "category", "billing", "updated_at", "2026-07-20")));

        Response response = resource.status("TKT-00013");

        assertEquals(200, response.getStatus());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals("TKT-00013", body.get("ref"));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> tickets = (List<Map<String, Object>>) body.get("tickets");
        assertEquals(2, tickets.size());
    }

    @Test
    void ticketNumberLookupIsCaseInsensitive() {
        when(db.listTickets("ticketNumber=tkt-00013")).thenReturn(List.of(Map.of(
                "id", "tkt-id-13", "ticket_number", "TKT-00013", "tenant_id", "t1", "identity_id", "m-1")));
        when(db.listTickets("tenantId=t1&identityId=m-1")).thenReturn(List.of(
                Map.of("ticket_number", "TKT-00013", "status", "open", "category", "outage", "updated_at", "2026-08-01")));

        Response response = resource.status("tkt-00013");

        assertEquals(200, response.getStatus());
    }

    @Test
    void ticketNumberLookupFallsBackToJustThatTicketWhenIdentityNotYetLinked() {
        // A ticket still in the intake/pending stage has no identity_id yet --
        // must not crash, and must still return the one ticket it does have.
        when(db.listTickets("ticketNumber=TKT-00099")).thenReturn(List.of(Map.of(
                "id", "tkt-id-99", "ticket_number", "TKT-00099", "tenant_id", "t1",
                "status", "open", "category", "other")));

        Response response = resource.status("TKT-00099");

        assertEquals(200, response.getStatus());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> tickets = (List<Map<String, Object>>) body.get("tickets");
        assertEquals(1, tickets.size());
        assertEquals("TKT-00099", tickets.get(0).get("ticketNumber"));
        verify(db, never()).findIdentityByAnonRef(org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void ticketNumberLookupReturns404WhenTicketDoesNotExist() {
        when(db.listTickets("ticketNumber=TKT-99999")).thenReturn(List.of());

        Response response = resource.status("TKT-99999");

        assertEquals(404, response.getStatus());
    }

    @Test
    void emailLookupPathIsUnchanged() {
        when(db.findIdentityByEmail("t1", "citizen@example.org")).thenReturn(
                Optional.of(Map.of("tenant_id", "t1", "master_id", "m-2", "is_anonymous", 0)));
        when(db.listTickets("tenantId=t1&identityId=m-2")).thenReturn(List.of());

        Response response = resource.status("citizen@example.org");

        assertEquals(200, response.getStatus());
        verify(db, never()).listTickets(org.mockito.ArgumentMatchers.startsWith("ticketNumber="));
    }

    @Test
    void anonRefLookupPathIsUnchanged() {
        when(db.findIdentityByAnonRef("ANON-1234")).thenReturn(
                Optional.of(Map.of("tenant_id", "t1", "master_id", "m-3", "is_anonymous", 1)));
        when(db.listTickets("tenantId=t1&identityId=m-3")).thenReturn(List.of());

        Response response = resource.status("ANON-1234");

        assertEquals(200, response.getStatus());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals(Boolean.TRUE, body.get("isAnonymous"));
    }

    @Test
    void anonRefLookupReturns404WhenNotFound() {
        when(db.findIdentityByAnonRef("ANON-NOPE")).thenReturn(Optional.empty());

        Response response = resource.status("ANON-NOPE");

        assertEquals(404, response.getStatus());
    }
}
