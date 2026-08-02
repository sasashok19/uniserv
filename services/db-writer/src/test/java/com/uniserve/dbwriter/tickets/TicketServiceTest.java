package com.uniserve.dbwriter.tickets;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Pure-function tests for {@link TicketService#buildWhere} (Feature 19: origin-message-id
 * lookup, used for WhatsApp swipe-reply / email In-Reply-To ticket matching). No database
 * needed -- buildWhere only assembles a WHERE-clause string and a params map. */
class TicketServiceTest {

    @Test
    void originMessageIdAddsExactMatchClauseAndParam() {
        Map<String, Object> params = new HashMap<>();
        String where = TicketService.buildWhere(
                "t1", null, null, null, null, null, null, null, null,
                "wamid.ABC123", false, params);

        assertTrue(where.contains("t.origin_message_id = :originMessageId"));
        assertEquals("wamid.ABC123", params.get("originMessageId"));
    }

    @Test
    void blankOrNullOriginMessageIdAddsNoClause() {
        Map<String, Object> paramsNull = new HashMap<>();
        String whereNull = TicketService.buildWhere(
                "t1", null, null, null, null, null, null, null, null,
                null, false, paramsNull);
        assertFalse(whereNull.contains("origin_message_id"));
        assertFalse(paramsNull.containsKey("originMessageId"));

        Map<String, Object> paramsBlank = new HashMap<>();
        String whereBlank = TicketService.buildWhere(
                "t1", null, null, null, null, null, null, null, null,
                "  ", false, paramsBlank);
        assertFalse(whereBlank.contains("origin_message_id"));
    }

    @Test
    void originMessageIdComposesWithOtherFilters() {
        Map<String, Object> params = new HashMap<>();
        String where = TicketService.buildWhere(
                "t1", "open,in_progress", null, null, null, null, null, null, null,
                "wamid.XYZ", false, params);

        assertTrue(where.contains("t.tenant_id = :tenantId"));
        assertTrue(where.contains("t.status in (:statuses)"));
        assertTrue(where.contains("t.origin_message_id = :originMessageId"));
        assertTrue(where.contains("t.archived_at is null"));
        assertEquals("t1", params.get("tenantId"));
        assertEquals("wamid.XYZ", params.get("originMessageId"));
    }

    @Test
    void includeArchivedOmitsArchivedFilterRegardlessOfOriginMessageId() {
        Map<String, Object> params = new HashMap<>();
        String where = TicketService.buildWhere(
                "t1", null, null, null, null, null, null, null, null,
                "wamid.ABC123", true, params);

        assertFalse(where.contains("archived_at"));
        assertTrue(where.contains("origin_message_id"));
    }
}
