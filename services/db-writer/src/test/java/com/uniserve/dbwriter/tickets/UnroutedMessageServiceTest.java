package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Ticket;
import com.uniserve.dbwriter.model.TicketMessage;
import com.uniserve.dbwriter.model.UnroutedMessage;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 24: the unrouted-message queue.
 *
 * These messages exist because the alternatives are worse. Dropping a citizen's
 * words loses them entirely — nobody can fix what was never stored — and minting
 * a placeholder ticket puts permanent noise in the queue. So they are kept here,
 * and an agent either files them against the right ticket or marks them noise.
 */
@QuarkusTest
class UnroutedMessageServiceTest {

    @Inject
    UnroutedMessageService unrouted;

    @Inject
    TicketService tickets;

    private static final String TENANT = "t1";

    private Map<String, Object> park(String content, String status, int askCount) {
        return unrouted.create(Map.of(
                "tenantId", TENANT, "channel", "whatsapp",
                "channelIdentityValue", "+9190000" + UUID.randomUUID().toString().substring(0, 5),
                "content", content, "reason", "not an answer and not a complaint",
                "status", status, "askCount", askCount));
    }

    @Test
    void aParkedMessageKeepsTheCitizensExactWords() {
        Map<String, Object> parked = park("Yes it is", UnroutedMessage.PENDING, 1);

        assertNotNull(parked.get("id"));
        assertEquals("Yes it is", parked.get("content"));
        assertEquals(UnroutedMessage.PENDING, parked.get("status"));
        assertEquals(1, parked.get("ask_count"));
        assertNull(parked.get("resolved_ticket_id"));
    }

    @Test
    void contentIsRequiredBecauseAnEmptyRowHelpsNobody() {
        assertThrows(ApiException.class, () -> unrouted.create(Map.of(
                "tenantId", TENANT, "channel", "whatsapp", "content", "   ")));
    }

    @Test
    void aNewRowMayNotBeCreatedAlreadyResolved() {
        // `attached`/`discarded` are outcomes of an agent's decision, so they
        // cannot be asserted by the writer.
        assertThrows(ApiException.class, () -> unrouted.create(Map.of(
                "tenantId", TENANT, "channel", "whatsapp", "content", "ok",
                "status", UnroutedMessage.ATTACHED)));
    }

    @Test
    void attachingCopiesTheMessageOntoTheTicketsConversation() {
        // The point of resolving one is to DELIVER the message, not just to
        // clear the queue — so the text has to land where an agent reading the
        // ticket will actually see it.
        Map<String, Object> ticket = tickets.create(Map.of(
                "tenantId", TENANT, "channelOrigin", "whatsapp"));
        String ticketId = String.valueOf(ticket.get("id"));
        Map<String, Object> parked = park("Yes it is", UnroutedMessage.PENDING, 1);

        Map<String, Object> resolved = unrouted.attach(
                String.valueOf(parked.get("id")), ticketId, "agent-1");

        assertEquals(UnroutedMessage.ATTACHED, resolved.get("status"));
        assertEquals(ticketId, resolved.get("resolved_ticket_id"));
        assertEquals("agent-1", resolved.get("resolved_by"));

        List<Map<String, Object>> messages = tickets.messages(ticketId);
        assertEquals(1, messages.size());
        assertEquals("Yes it is", messages.get(0).get("content"));
        assertEquals("inbound", messages.get(0).get("direction"));
        assertEquals("user", messages.get(0).get("author_type"));
    }

    @Test
    void attachingAnUnknownTicketIsRejected() {
        Map<String, Object> parked = park("ok", UnroutedMessage.PENDING, 1);
        assertThrows(ApiException.class,
                () -> unrouted.attach(String.valueOf(parked.get("id")), "no-such-ticket", "agent-1"));
    }

    @Test
    void aMessageCannotBeResolvedTwice() {
        Map<String, Object> ticket = tickets.create(Map.of(
                "tenantId", TENANT, "channelOrigin", "whatsapp"));
        Map<String, Object> parked = park("ok", UnroutedMessage.PENDING, 1);
        String id = String.valueOf(parked.get("id"));

        unrouted.discard(id, "agent-1");

        assertThrows(ApiException.class,
                () -> unrouted.attach(id, String.valueOf(ticket.get("id")), "agent-2"));
        assertThrows(ApiException.class, () -> unrouted.discard(id, "agent-2"));
    }

    @Test
    void discardingKeepsTheRowRatherThanDeletingIt() {
        Map<String, Object> parked = park("thanks", UnroutedMessage.PENDING, 1);

        Map<String, Object> resolved = unrouted.discard(String.valueOf(parked.get("id")), "agent-1");

        assertEquals(UnroutedMessage.DISCARDED, resolved.get("status"));
        assertEquals("thanks", resolved.get("content"));
    }

    @Test
    void theQueueListsOnlyTheStatusesAskedFor() {
        park("pending one", UnroutedMessage.PENDING, 1);
        park("escalated one", UnroutedMessage.ESCALATED, 0);

        List<Map<String, Object>> pendingOnly = unrouted.list(TENANT, UnroutedMessage.PENDING, 1, 50);
        assertTrue(pendingOnly.stream().allMatch(m -> UnroutedMessage.PENDING.equals(m.get("status"))));

        List<Map<String, Object>> both = unrouted.list(TENANT, "pending,escalated", 1, 50);
        assertTrue(both.size() >= 2);
        assertEquals(both.size(), unrouted.count(TENANT, "pending,escalated"));
    }

    @Test
    void theAskCountLookupIsWhatStopsTheClarifyLoop() {
        // "Send us your ticket number" -> "I don't have it" is ALSO unroutable.
        // ai-core reads this to escalate instead of asking a second time.
        // Unique per run, like `park` above: @QuarkusTest writes to a real,
        // persistent uniserve.db, so a fixed contact accumulates a row on every
        // execution and this assertion only ever held on a virgin database.
        String contact = "+9190000" + UUID.randomUUID().toString().substring(0, 5);
        unrouted.create(Map.of("tenantId", TENANT, "channel", "whatsapp",
                "channelIdentityValue", contact, "content", "yes", "askCount", 1));

        assertEquals(1, unrouted.recentAskCount(TENANT, contact, "2000-01-01 00:00:00"));
        // A window that starts in the future excludes it, which is how the
        // lookback keeps a citizen from being exempt forever.
        assertEquals(0, unrouted.recentAskCount(TENANT, contact, "2999-01-01 00:00:00"));
        assertEquals(0, unrouted.recentAskCount(TENANT, "+910000000000", "2000-01-01 00:00:00"));
        assertEquals(0, unrouted.recentAskCount(TENANT, null, "2000-01-01 00:00:00"));
    }
}
