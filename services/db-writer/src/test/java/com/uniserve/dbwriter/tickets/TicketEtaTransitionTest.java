package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 26: an ETA is mandatory as part of the first transition.
 *
 * The whole point of the rule is that a citizen asking "when will this be
 * fixed?" gets an answer, so the enforcement lives here — in the single
 * transition entry point every caller goes through — rather than in the
 * dashboard, which is only one of them.
 */
@QuarkusTest
class TicketEtaTransitionTest {

    @Inject
    TicketService tickets;

    private static final String TENANT = "t1";

    private static String daysFromNow(int days) {
        return DateTimeFormatter.ofPattern("yyyy-MM-dd").withZone(ZoneOffset.UTC)
                .format(Instant.now().plus(days, ChronoUnit.DAYS));
    }

    private String newTicket() {
        return String.valueOf(tickets.create(Map.of(
                "tenantId", TENANT, "channelOrigin", "whatsapp")).get("id"));
    }

    private static Map<String, Object> body(String toStatus, String eta, String note) {
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("toStatus", toStatus);
        if (eta != null) {
            b.put("eta", eta);
        }
        if (note != null) {
            b.put("noteContent", note);
            b.put("agentId", "agent-1");
        }
        return b;
    }

    private Map<String, Object> read(String id) {
        return tickets.getById(id).orElseThrow();
    }

    // --- the rule ---------------------------------------------------------

    @Test
    void theFirstTransitionIsRefusedWithoutAnEta() {
        String id = newTicket();

        ApiException e = assertThrows(ApiException.class,
                () -> tickets.transition(id, body("assigned", null, null)));

        assertEquals(422, e.status());
        assertEquals("ETA_REQUIRED", e.code());
        assertEquals("open", read(id).get("status"), "a refused transition must not move the ticket");
    }

    @Test
    void theFirstTransitionSucceedsWithAnEtaAndStampsBothColumns() {
        String id = newTicket();

        Map<String, Object> result = tickets.transition(id, body("assigned", daysFromNow(3), null));

        assertEquals("assigned", result.get("status"));
        Map<String, Object> ticket = read(id);
        assertEquals(daysFromNow(3) + " 23:59:59", ticket.get("eta_at"));
        assertNotNull(ticket.get("first_transition_at"));
    }

    @Test
    void laterTransitionsDoNotDemandTheEtaAgain() {
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));

        tickets.transition(id, body("in_progress", null, null));

        assertEquals("in_progress", read(id).get("status"));
    }

    @Test
    void aRefusedTransitionDoesNotBurnTheOneChanceToDemandAnEta() {
        // first_transition_at must be stamped only AFTER every check passes —
        // otherwise a rejected attempt would excuse the ETA forever after.
        String id = newTicket();
        assertThrows(ApiException.class, () -> tickets.transition(id, body("assigned", null, null)));

        assertNull(read(id).get("first_transition_at"));
        ApiException again = assertThrows(ApiException.class,
                () -> tickets.transition(id, body("assigned", null, null)));
        assertEquals("ETA_REQUIRED", again.code());
    }

    @Test
    void aTransitionRefusedForItsNoteDoesNotStampTheEtaEither() {
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));
        tickets.transition(id, body("in_progress", null, null));

        // in_progress -> resolved needs a >=20 char note.
        assertThrows(ApiException.class,
                () -> tickets.transition(id, body("resolved", daysFromNow(9), "too short")));

        assertEquals(daysFromNow(3) + " 23:59:59", read(id).get("eta_at"),
                "a rejected transition must not quietly change the promise");
    }

    // --- cancelling is exempt ---------------------------------------------

    @Test
    void cancellingNeedsNoEtaBecauseNoWorkIsBeingPromised() {
        String id = newTicket();

        tickets.transition(id, body("cancelled", null,
                "Duplicate of an earlier report, withdrawn by the citizen."));

        Map<String, Object> ticket = read(id);
        assertEquals("cancelled", ticket.get("status"));
        assertNull(ticket.get("eta_at"));
        // It is still a first transition, so it is still stamped as one.
        assertNotNull(ticket.get("first_transition_at"));
    }

    // --- validation reaches the transition path ---------------------------

    @Test
    void anInvalidEtaIsRejectedRatherThanStored() {
        String id = newTicket();

        ApiException e = assertThrows(ApiException.class,
                () -> tickets.transition(id, body("assigned", "next tuesday", null)));

        assertEquals("ETA_INVALID", e.code());
        assertEquals("open", read(id).get("status"));
    }

    @Test
    void aPastEtaIsRejectedOnTheTransitionPath() {
        String id = newTicket();

        assertEquals("ETA_IN_PAST", assertThrows(ApiException.class,
                () -> tickets.transition(id, body("assigned", "2020-01-01", null))).code());
    }

    // --- revising later ---------------------------------------------------

    @Test
    void revisingTheEtaIsAllowedAndAudited() {
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));

        tickets.update(id, Map.of("eta", daysFromNow(10), "actorAgentId", "agent-1"));

        assertEquals(daysFromNow(10) + " 23:59:59", read(id).get("eta_at"));
        assertTrue(tickets.events(id).stream()
                        .anyMatch(e -> "ticket.eta_changed".equals(e.get("event_type"))),
                "a promise made to a citizen cannot change without a record of it");
    }

    @Test
    void clearingTheEtaDoesNotReArmTheFirstTransitionRule() {
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));

        Map<String, Object> clear = new LinkedHashMap<>();
        clear.put("eta", null);
        Map<String, Object> cleared = tickets.update(id, clear);
        assertNull(cleared.get("eta_at"));

        // first_transition_at is still stamped, so this must NOT throw. Asserted
        // on the transition's own return value rather than a re-read: these
        // service calls each run in their own transaction while the test does
        // not, so an intervening getById can hand back a stale managed entity.
        assertEquals("in_progress", tickets.transition(id, body("in_progress", null, null)).get("status"));
    }

    @Test
    void anUnchangedEtaWritesNoAuditNoise() {
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));
        long before = tickets.events(id).stream()
                .filter(e -> "ticket.eta_changed".equals(e.get("event_type"))).count();

        tickets.update(id, Map.of("eta", daysFromNow(3)));

        assertEquals(before, tickets.events(id).stream()
                .filter(e -> "ticket.eta_changed".equals(e.get("event_type"))).count());
    }

    // --- the ETA travels with the ticket ----------------------------------

    @Test
    void theEtaIsReadableFromTheQueueListingNotJustTheDetailRow() {
        // The citizen-facing "when will this be done?" read and the agent
        // queue's overdue view both come off the list projection.
        String id = newTicket();
        tickets.transition(id, body("assigned", daysFromNow(3), null));

        Map<String, Object> listed = tickets.list(TENANT, null, null, null, null, null, null, null,
                        String.valueOf(read(id).get("ticket_number")), null, false, 1, 10, null, null)
                .get(0);

        assertEquals(daysFromNow(3) + " 23:59:59", listed.get("eta_at"));
    }

    @Test
    void anEtaCanBeSetAtCreationForImportsWithoutACreateThenPatch() {
        String id = String.valueOf(tickets.create(Map.of(
                "tenantId", TENANT, "channelOrigin", "email", "eta", daysFromNow(5))).get("id"));

        assertEquals(daysFromNow(5) + " 23:59:59", read(id).get("eta_at"));
    }
}
