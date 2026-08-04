package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 24: recording and looking up the provider's id for a message.
 *
 * This is routing rung 0 — the exact, heuristic-free answer to "which ticket is
 * the citizen replying on". Its absence is why a reply of "Yes it is" had to be
 * matched by inference and ended up on the wrong ticket.
 */
@QuarkusTest
class MessageChannelIdTest {

    @Inject
    TicketService tickets;

    private static final String TENANT = "t1";

    private String newTicket() {
        return String.valueOf(tickets.create(Map.of(
                "tenantId", TENANT, "channelOrigin", "whatsapp")).get("id"));
    }

    @Test
    void aSentMessageIsStampedWithTheProvidersIdAndFoundByIt() {
        String ticketId = newTicket();
        String wamid = "wamid." + UUID.randomUUID();
        // The row exists BEFORE the send (so a failed send still records what we
        // tried to say); the id only exists after it.
        Map<String, Object> message = tickets.addMessage(ticketId, Map.of(
                "direction", "outbound", "authorType", "agent", "content", "Is this resolved?"));

        tickets.setMessageChannelId(String.valueOf(message.get("id")), wamid);

        Optional<Map<String, Object>> found = tickets.findByChannelMessageId(TENANT, wamid);
        assertTrue(found.isPresent());
        assertEquals(ticketId, found.get().get("ticket_id"));
        assertEquals("Is this resolved?", found.get().get("content"));
    }

    @Test
    void anInboundMessageMayCarryItsProviderIdFromTheStart() {
        String ticketId = newTicket();
        String wamid = "wamid." + UUID.randomUUID();

        tickets.addMessage(ticketId, Map.of(
                "direction", "inbound", "authorType", "user", "content", "No power",
                "channelMessageId", wamid));

        assertEquals(ticketId, tickets.findByChannelMessageId(TENANT, wamid).orElseThrow().get("ticket_id"));
    }

    @Test
    void anUnknownOrBlankIdIsAMissNotAnError() {
        // Most inbound messages are not replies, so a miss is the normal case.
        assertTrue(tickets.findByChannelMessageId(TENANT, "wamid.never-seen").isEmpty());
        assertTrue(tickets.findByChannelMessageId(TENANT, "").isEmpty());
        assertTrue(tickets.findByChannelMessageId(TENANT, null).isEmpty());
    }

    @Test
    void theLookupIsTenantScoped() {
        String ticketId = newTicket();
        String wamid = "wamid." + UUID.randomUUID();
        Map<String, Object> message = tickets.addMessage(ticketId, Map.of(
                "direction", "outbound", "authorType", "agent", "content", "x"));
        tickets.setMessageChannelId(String.valueOf(message.get("id")), wamid);

        assertTrue(tickets.findByChannelMessageId("some-other-tenant", wamid).isEmpty());
    }

    @Test
    void stampingRejectsAnEmptyIdAndAnUnknownMessage() {
        String ticketId = newTicket();
        Map<String, Object> message = tickets.addMessage(ticketId, Map.of(
                "direction", "outbound", "authorType", "agent", "content", "x"));

        assertThrows(ApiException.class,
                () -> tickets.setMessageChannelId(String.valueOf(message.get("id")), " "));
        assertThrows(ApiException.class,
                () -> tickets.setMessageChannelId("no-such-message", "wamid.abc"));
    }

    @Test
    void anIntakeRequestIsMarkedSoTheIntakeGuardCanTrustIt() {
        // A bare "yes" is structurally identical whether it answers "did you mean
        // x@gmail.com?" or "is this resolved?". The intake guard may only claim
        // such a message where an intake question was actually asked.
        String ticketId = newTicket();

        tickets.addMessage(ticketId, Map.of(
                "direction", "outbound", "authorType", "ai", "content", "What is your name?",
                "isIntakeRequest", 1));
        tickets.addMessage(ticketId, Map.of(
                "direction", "outbound", "authorType", "agent", "content", "Is this resolved?"));

        var messages = tickets.messages(ticketId);
        assertEquals(1, messages.get(0).get("is_intake_request"));
        assertEquals(0, messages.get(1).get("is_intake_request"));
    }
}
