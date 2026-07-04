package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.db.Db;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * Ticket CRUD + status transitions (Feature 04). All writes go through here;
 * reads for a single ticket are cached in {@link TicketCache}.
 */
@ApplicationScoped
public class TicketService {

    /** Transitions that require a substantive (>=20 char) note. */
    private static final Set<String> MANDATORY_NOTE_TRANSITIONS = Set.of(
            "in_progress->resolved",
            "resolved->closed",
            "closed->reopened");

    @Inject
    Db db;

    @Inject
    TicketCache cache;

    /** Create a ticket; ticket_number is sequential per tenant (TKT-00001, ...). */
    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        if (tenantId == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String channelOrigin = str(body, "channelOrigin");
        if (channelOrigin == null) {
            throw new ApiException(400, "CHANNEL_REQUIRED", "channelOrigin is required");
        }

        String id = UUID.randomUUID().toString();
        String ticketNumber = nextTicketNumber(tenantId);

        db.update("""
                INSERT INTO tickets
                  (id, tenant_id, ticket_number, identity_id, identity_status, identity_source,
                   assigned_to, status, category, subcategory, priority_score, priority_label,
                   sentiment_score, channel_origin, is_duplicate, parent_ticket_id, sla_due_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                id, tenantId, ticketNumber,
                str(body, "identityId"),
                strOr(body, "identityStatus", "pending"),
                str(body, "identitySource"),
                str(body, "assignedTo"),
                strOr(body, "status", "open"),
                str(body, "category"),
                str(body, "subcategory"),
                num(body, "priorityScore"),
                str(body, "priorityLabel"),
                num(body, "sentimentScore"),
                channelOrigin,
                intOr(body, "isDuplicate", 0),
                str(body, "parentTicketId"),
                str(body, "slaDueAt"));

        event(tenantId, id, "ticket.created", "system", null);
        return getById(id).orElseThrow();
    }

    public Optional<Map<String, Object>> getById(String id) {
        return db.queryOne("SELECT * FROM tickets WHERE id = ?", id);
    }

    /** Read-through cache: returns the ticket and whether it was a cache hit. */
    public CacheResult getCached(String id) {
        Map<String, Object> cached = cache.getIfPresent(id);
        if (cached != null) {
            return new CacheResult(cached, true);
        }
        Optional<Map<String, Object>> row = getById(id);
        row.ifPresent(t -> cache.put(id, t));
        return new CacheResult(row.orElse(null), false);
    }

    public record CacheResult(Map<String, Object> ticket, boolean hit) {
    }

    public List<Map<String, Object>> list(String tenantId, String status, String assignedTo,
                                          String channel, String category, String identityId,
                                          int page, int pageSize) {
        StringBuilder sql = new StringBuilder("SELECT * FROM tickets WHERE tenant_id = ?");
        List<Object> params = new java.util.ArrayList<>();
        params.add(tenantId);
        if (status != null && !status.isBlank()) {
            List<String> vals = List.of(status.split(","));
            sql.append(" AND status IN (").append("?,".repeat(vals.size() - 1)).append("?)");
            params.addAll(vals);
        }
        if (assignedTo != null && !assignedTo.isBlank()) {
            sql.append(" AND assigned_to = ?");
            params.add(assignedTo);
        }
        if (identityId != null && !identityId.isBlank()) {
            sql.append(" AND identity_id = ?");
            params.add(identityId);
        }
        if (channel != null && !channel.isBlank()) {
            sql.append(" AND channel_origin = ?");
            params.add(channel);
        }
        if (category != null && !category.isBlank()) {
            sql.append(" AND category = ?");
            params.add(category);
        }
        sql.append(" ORDER BY priority_score DESC LIMIT ? OFFSET ?");
        params.add(pageSize);
        params.add((page - 1) * pageSize);
        return db.query(sql.toString(), params.toArray());
    }

    public Map<String, Object> update(String id, Map<String, Object> body) {
        Map<String, Object> ticket = getById(id)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "ticket not found: " + id));
        // Whitelist of updatable columns (camelCase -> snake_case).
        Map<String, String> updatable = Map.of(
                "status", "status", "category", "category", "subcategory", "subcategory",
                "priorityScore", "priority_score", "priorityLabel", "priority_label",
                "assignedTo", "assigned_to", "resolution", "resolution", "slaDueAt", "sla_due_at");
        for (Map.Entry<String, String> e : updatable.entrySet()) {
            if (body.containsKey(e.getKey())) {
                db.update("UPDATE tickets SET " + e.getValue() + " = ?, updated_at = datetime('now') WHERE id = ?",
                        body.get(e.getKey()), id);
            }
        }
        cache.invalidate(id);
        return getById(id).orElseThrow();
    }

    /** Perform a status transition with mandatory-note enforcement. */
    public Map<String, Object> transition(String id, Map<String, Object> body) {
        Map<String, Object> ticket = getById(id)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "ticket not found: " + id));

        String fromStatus = strOr(body, "fromStatus", String.valueOf(ticket.get("status")));
        String toStatus = str(body, "toStatus");
        if (toStatus == null) {
            throw new ApiException(400, "TO_STATUS_REQUIRED", "toStatus is required");
        }
        String noteContent = str(body, "noteContent");
        String agentId = str(body, "agentId");
        String transitionKey = fromStatus + "->" + toStatus;

        if (MANDATORY_NOTE_TRANSITIONS.contains(transitionKey)) {
            if (noteContent == null || noteContent.trim().length() < 20) {
                throw new ApiException(422, "NOTE_TOO_SHORT",
                        "Note must be at least 20 characters for " + transitionKey + " transition");
            }
        }

        String tenantId = String.valueOf(ticket.get("tenant_id"));

        // Record the mandatory note (when supplied with an agent).
        if (noteContent != null && !noteContent.isBlank() && agentId != null) {
            db.update("""
                    INSERT INTO ticket_notes
                      (id, tenant_id, ticket_id, agent_id, content, is_mandatory, transition_from, transition_to)
                    VALUES (?,?,?,?,?,1,?,?)
                    """,
                    UUID.randomUUID().toString(), tenantId, id, agentId, noteContent, fromStatus, toStatus);
        }

        // Apply the status change and side effects.
        db.update("UPDATE tickets SET status = ?, updated_at = datetime('now') WHERE id = ?", toStatus, id);
        if ("resolved".equals(toStatus)) {
            db.update("UPDATE tickets SET resolved_at = datetime('now') WHERE id = ?", id);
        } else if ("closed".equals(toStatus)) {
            db.update("UPDATE tickets SET closed_at = datetime('now') WHERE id = ?", id);
        } else if ("reopened".equals(toStatus)) {
            // Clear resolution, bump counter, record who reopened — assignee preserved.
            db.update("""
                    UPDATE tickets
                       SET resolution = NULL,
                           resolved_at = NULL,
                           closed_at = NULL,
                           reopened_count = reopened_count + 1,
                           reopened_by = ?
                     WHERE id = ?
                    """, agentId, id);
        }

        event(tenantId, id, "status." + toStatus, agentId == null ? "system" : "agent", agentId);
        cache.invalidate(id);

        Map<String, Object> updated = getById(id).orElseThrow();
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        result.put("status", toStatus);
        result.put("resolvedAt", updated.get("resolved_at"));
        return result;
    }

    public Map<String, Object> addNote(String id, Map<String, Object> body) {
        Map<String, Object> ticket = getById(id)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "ticket not found: " + id));
        String agentId = str(body, "agentId");
        String content = str(body, "content");
        if (content == null || content.trim().isEmpty()) {
            throw new ApiException(422, "NOTE_EMPTY", "Note content is required");
        }
        String noteId = UUID.randomUUID().toString();
        db.update("""
                INSERT INTO ticket_notes (id, tenant_id, ticket_id, agent_id, content, is_mandatory)
                VALUES (?,?,?,?,?,0)
                """, noteId, ticket.get("tenant_id"), id, agentId, content);
        return db.queryOne("SELECT * FROM ticket_notes WHERE id = ?", noteId).orElseThrow();
    }

    public List<Map<String, Object>> messages(String id) {
        return db.query("SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at", id);
    }

    public List<Map<String, Object>> notes(String id) {
        return db.query("SELECT * FROM ticket_notes WHERE ticket_id = ? ORDER BY created_at", id);
    }

    public List<Map<String, Object>> events(String id) {
        return db.query("SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY created_at", id);
    }

    /**
     * AI resolution summary (Feature 04). PHASE_1: the AI summariser (ai-core
     * feature 06+) is not wired to db-writer yet, so this always reports the
     * documented "AI unavailable" fallback.
     */
    public Map<String, Object> resolutionSummary(String id) {
        getById(id).orElseThrow(() -> new ApiException(404, "NOT_FOUND", "ticket not found: " + id));
        throw new ApiException(503, "AI_UNAVAILABLE",
                "AI summary unavailable. Please write resolution manually.");
    }

    // ---- helpers ---------------------------------------------------------

    private String nextTicketNumber(String tenantId) {
        Object max = db.scalar(
                "SELECT MAX(CAST(SUBSTR(ticket_number, 5) AS INTEGER)) FROM tickets WHERE tenant_id = ?",
                tenantId);
        int next = (max == null ? 0 : ((Number) max).intValue()) + 1;
        return String.format("TKT-%05d", next);
    }

    private void event(String tenantId, String ticketId, String type, String actorType, String actorId) {
        db.update("""
                INSERT INTO ticket_events (id, tenant_id, ticket_id, event_type, actor_type, actor_id)
                VALUES (?,?,?,?,?,?)
                """, UUID.randomUUID().toString(), tenantId, ticketId, type, actorType, actorId);
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static String strOr(Map<String, Object> body, String key, String fallback) {
        String v = str(body, key);
        return v == null ? fallback : v;
    }

    private static Double num(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? null : ((Number) v).doubleValue();
    }

    private static int intOr(Map<String, Object> body, String key, int fallback) {
        Object v = body.get(key);
        return v == null ? fallback : ((Number) v).intValue();
    }
}
