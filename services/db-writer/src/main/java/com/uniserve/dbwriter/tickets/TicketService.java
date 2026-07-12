package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Ticket;
import com.uniserve.dbwriter.model.TicketEvent;
import com.uniserve.dbwriter.model.TicketMessage;
import com.uniserve.dbwriter.model.TicketNote;
import com.uniserve.dbwriter.util.SqliteTime;
import io.quarkus.hibernate.orm.panache.Panache;
import io.quarkus.panache.common.Page;
import io.quarkus.panache.common.Sort;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.transaction.Transactional;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * Ticket CRUD + status transitions (Feature 04), backed by Hibernate ORM with
 * Panache (active-record entities under {@code com.uniserve.dbwriter.model}).
 * Reads for a single ticket are cached in {@link TicketCache}.
 */
@ApplicationScoped
public class TicketService {

    /** Transitions that require a substantive (>=20 char) note. */
    private static final Set<String> MANDATORY_NOTE_TRANSITIONS = Set.of(
            "in_progress->resolved",
            "resolved->closed",
            "closed->reopened");

    @Inject
    TicketCache cache;

    /** Create a ticket; ticket_number is sequential per tenant (TKT-00001, ...). */
    @Transactional
    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        if (tenantId == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String channelOrigin = str(body, "channelOrigin");
        if (channelOrigin == null) {
            throw new ApiException(400, "CHANNEL_REQUIRED", "channelOrigin is required");
        }

        Ticket t = new Ticket();
        t.id = UUID.randomUUID().toString();
        t.tenantId = tenantId;
        t.ticketNumber = nextTicketNumber(tenantId);
        t.identityId = str(body, "identityId");
        t.identityStatus = strOr(body, "identityStatus", "pending");
        t.identitySource = str(body, "identitySource");
        t.assignedTo = str(body, "assignedTo");
        t.status = strOr(body, "status", "open");
        t.category = str(body, "category");
        t.subcategory = str(body, "subcategory");
        t.priorityScore = num(body, "priorityScore");
        t.priorityLabel = str(body, "priorityLabel");
        t.sentimentScore = num(body, "sentimentScore");
        t.channelOrigin = channelOrigin;
        t.threadId = str(body, "threadId");
        t.isDuplicate = intOr(body, "isDuplicate", 0);
        t.parentTicketId = str(body, "parentTicketId");
        t.serviceId = str(body, "serviceId");
        t.slaDueAt = str(body, "slaDueAt");
        // Flush immediately so any CHECK-constraint violation (bad status/priority
        // label/etc.) surfaces here rather than being deferred to commit time.
        t.persistAndFlush();

        recordEvent(tenantId, t.id, "ticket.created", "system", null);
        return t.toMap();
    }

    public Optional<Map<String, Object>> getById(String id) {
        Ticket t = Ticket.findById(id);
        return Optional.ofNullable(t).map(Ticket::toMap);
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
                                          String identityStatus, String threadId, String ticketNumber,
                                          boolean includeArchived, int page, int pageSize) {
        StringBuilder query = new StringBuilder("tenantId = :tenantId");
        Map<String, Object> params = new HashMap<>();
        params.put("tenantId", tenantId);
        if (status != null && !status.isBlank()) {
            query.append(" and status in :statuses");
            params.put("statuses", List.of(status.split(",")));
        }
        if (assignedTo != null && !assignedTo.isBlank()) {
            query.append(" and assignedTo = :assignedTo");
            params.put("assignedTo", assignedTo);
        }
        if (identityId != null && !identityId.isBlank()) {
            query.append(" and identityId = :identityId");
            params.put("identityId", identityId);
        }
        if (identityStatus != null && !identityStatus.isBlank()) {
            query.append(" and identityStatus in :identityStatuses");
            params.put("identityStatuses", List.of(identityStatus.split(",")));
        }
        if (threadId != null && !threadId.isBlank()) {
            query.append(" and threadId = :threadId");
            params.put("threadId", threadId);
        }
        if (ticketNumber != null && !ticketNumber.isBlank()) {
            query.append(" and ticketNumber = :ticketNumber");
            params.put("ticketNumber", ticketNumber);
        }
        if (channel != null && !channel.isBlank()) {
            query.append(" and channelOrigin = :channel");
            params.put("channel", channel);
        }
        if (category != null && !category.isBlank()) {
            query.append(" and category = :category");
            params.put("category", category);
        }
        if (!includeArchived) {
            query.append(" and archivedAt is null");
        }

        List<Ticket> rows = Ticket.find(query.toString(), Sort.by("priorityScore", Sort.Direction.Descending), params)
                .page(Page.of(Math.max(page - 1, 0), pageSize))
                .list();
        return rows.stream().map(Ticket::toMap).toList();
    }

    /** Find the ticket already tracking this conversation thread, if any (Feature 06). */
    public Optional<Map<String, Object>> findByThreadId(String tenantId, String threadId) {
        return Ticket.<Ticket>find("tenantId = ?1 and threadId = ?2", tenantId, threadId)
                .firstResultOptional().map(Ticket::toMap);
    }

    @Transactional
    public Map<String, Object> update(String id, Map<String, Object> body) {
        Ticket t = Ticket.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        if (body.containsKey("status")) {
            t.status = str(body, "status");
        }
        if (body.containsKey("category")) {
            t.category = str(body, "category");
        }
        if (body.containsKey("subcategory")) {
            t.subcategory = str(body, "subcategory");
        }
        if (body.containsKey("priorityScore")) {
            t.priorityScore = num(body, "priorityScore");
        }
        if (body.containsKey("priorityLabel")) {
            t.priorityLabel = str(body, "priorityLabel");
        }
        if (body.containsKey("assignedTo")) {
            t.assignedTo = str(body, "assignedTo");
        }
        if (body.containsKey("resolution")) {
            t.resolution = str(body, "resolution");
        }
        if (body.containsKey("slaDueAt")) {
            t.slaDueAt = str(body, "slaDueAt");
        }
        if (body.containsKey("identityId")) {
            t.identityId = str(body, "identityId");
        }
        if (body.containsKey("identityStatus")) {
            t.identityStatus = str(body, "identityStatus");
        }
        if (body.containsKey("isDuplicate")) {
            t.isDuplicate = intOr(body, "isDuplicate", 0);
        }
        if (body.containsKey("parentTicketId")) {
            t.parentTicketId = str(body, "parentTicketId");
        }
        if (body.containsKey("serviceId")) {
            t.serviceId = str(body, "serviceId");
        }
        if (body.containsKey("archivedAt")) {
            t.archivedAt = str(body, "archivedAt");
        }
        cache.invalidate(id);
        // Force the flush (and the @PreUpdate updated_at refresh) before we read
        // the entity back into the response map.
        Panache.getEntityManager().flush();
        return t.toMap();
    }

    /** Perform a status transition with mandatory-note enforcement. */
    @Transactional
    public Map<String, Object> transition(String id, Map<String, Object> body) {
        Ticket t = Ticket.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }

        String fromStatus = strOr(body, "fromStatus", t.status);
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

        // Record the mandatory note (when supplied with an agent).
        if (noteContent != null && !noteContent.isBlank() && agentId != null) {
            TicketNote note = new TicketNote();
            note.id = UUID.randomUUID().toString();
            note.tenantId = t.tenantId;
            note.ticketId = t.id;
            note.agentId = agentId;
            note.content = noteContent;
            note.isMandatory = 1;
            note.transitionFrom = fromStatus;
            note.transitionTo = toStatus;
            note.persist();
        }

        // Apply the status change and side effects.
        t.status = toStatus;
        if ("resolved".equals(toStatus)) {
            t.resolvedAt = SqliteTime.now();
        } else if ("closed".equals(toStatus)) {
            t.closedAt = SqliteTime.now();
        } else if ("reopened".equals(toStatus)) {
            // Clear resolution, bump counter, record who reopened — assignee preserved.
            t.resolution = null;
            t.resolvedAt = null;
            t.closedAt = null;
            t.reopenedCount = (t.reopenedCount == null ? 0 : t.reopenedCount) + 1;
            t.reopenedBy = agentId;
        }

        recordEvent(t.tenantId, t.id, "status." + toStatus, agentId == null ? "system" : "agent", agentId);
        cache.invalidate(id);
        Panache.getEntityManager().flush();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", toStatus);
        result.put("resolvedAt", t.resolvedAt);
        return result;
    }

    @Transactional
    public Map<String, Object> addNote(String id, Map<String, Object> body) {
        Ticket t = Ticket.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        String agentId = str(body, "agentId");
        String content = str(body, "content");
        if (content == null || content.trim().isEmpty()) {
            throw new ApiException(422, "NOTE_EMPTY", "Note content is required");
        }
        TicketNote note = new TicketNote();
        note.id = UUID.randomUUID().toString();
        note.tenantId = t.tenantId;
        note.ticketId = id;
        note.agentId = agentId;
        note.content = content;
        note.isMandatory = 0;
        note.persistAndFlush();
        return note.toMap();
    }

    public List<Map<String, Object>> messages(String id) {
        return TicketMessage.<TicketMessage>find("ticketId", Sort.by("createdAt"), id)
                .list().stream().map(TicketMessage::toMap).toList();
    }

    /** Append a message (inbound citizen text or outbound AI/agent reply) to a ticket's timeline. */
    @Transactional
    public Map<String, Object> addMessage(String id, Map<String, Object> body) {
        Ticket t = Ticket.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        String content = str(body, "content");
        if (content == null || content.isBlank()) {
            throw new ApiException(422, "CONTENT_EMPTY", "Message content is required");
        }
        TicketMessage msg = new TicketMessage();
        msg.id = UUID.randomUUID().toString();
        msg.tenantId = t.tenantId;
        msg.ticketId = id;
        msg.channel = strOr(body, "channel", t.channelOrigin);
        msg.direction = strOr(body, "direction", "inbound");
        msg.authorType = strOr(body, "authorType", "user");
        msg.authorId = str(body, "authorId");
        msg.authorLabel = str(body, "authorLabel");
        msg.content = content;
        msg.isAiGenerated = intOr(body, "isAiGenerated", 0);
        msg.persistAndFlush();
        return msg.toMap();
    }

    public List<Map<String, Object>> notes(String id) {
        return TicketNote.<TicketNote>find("ticketId", Sort.by("createdAt"), id)
                .list().stream().map(TicketNote::toMap).toList();
    }

    public List<Map<String, Object>> events(String id) {
        return TicketEvent.<TicketEvent>find("ticketId", Sort.by("createdAt"), id)
                .list().stream().map(TicketEvent::toMap).toList();
    }

    /**
     * Archive (soft-delete) unconfirmed tickets older than {@code olderThanDays}
     * (Feature 12 admin cleanup): pending or anonymous identity status, not
     * already archived. Never physically deletes rows.
     */
    @Transactional
    public int archiveStale(String tenantId, int olderThanDays) {
        String cutoff = SqliteTime.minusDays(olderThanDays);
        List<Ticket> stale = Ticket.<Ticket>find(
                "tenantId = ?1 and identityStatus in ('pending','anonymous') and archivedAt is null "
                        + "and createdAt < ?2",
                tenantId, cutoff)
                .list();
        String now = SqliteTime.now();
        for (Ticket t : stale) {
            t.archivedAt = now;
            recordEvent(t.tenantId, t.id, "ticket.archived", "system", null);
            cache.invalidate(t.id);
        }
        Panache.getEntityManager().flush();
        return stale.size();
    }

    /**
     * Auto-close tickets still awaiting identity confirmation after
     * {@code olderThanDays} with no response (Feature 06 x 14) — distinct
     * from {@link #archiveStale}: this transitions {@code status} to
     * {@code closed} (with a system note) rather than soft-deleting, and
     * runs across every tenant since it's driven by a background schedule,
     * not an admin action. Returns the closed tickets so the caller (a
     * scheduled job in api-gateway) can notify each citizen.
     */
    @Transactional
    public List<Map<String, Object>> autoCloseUnconfirmed(int olderThanDays) {
        String cutoff = SqliteTime.minusDays(olderThanDays);
        List<Ticket> stale = Ticket.<Ticket>find(
                "identityStatus = 'pending' and archivedAt is null "
                        + "and status not in ('closed','resolved') and createdAt < ?1",
                cutoff)
                .list();
        String now = SqliteTime.now();
        List<Map<String, Object>> closed = new java.util.ArrayList<>();
        for (Ticket t : stale) {
            t.status = "closed";
            t.closedAt = now;
            recordEvent(t.tenantId, t.id, "ticket.auto_closed", "system", null);

            TicketNote note = new TicketNote();
            note.id = UUID.randomUUID().toString();
            note.tenantId = t.tenantId;
            note.ticketId = t.id;
            note.agentId = null;
            note.content = "Automatically closed after " + olderThanDays
                    + " days with no response to our identity verification request.";
            note.isMandatory = 1;
            note.transitionFrom = "pending";
            note.transitionTo = "closed";
            note.persist();

            cache.invalidate(t.id);
            closed.add(t.toMap());
        }
        Panache.getEntityManager().flush();
        return closed;
    }

    /**
     * AI resolution summary (Feature 04). PHASE_1: the AI summariser (ai-core
     * feature 06+) is not wired to db-writer yet, so this always reports the
     * documented "AI unavailable" fallback.
     */
    public Map<String, Object> resolutionSummary(String id) {
        if (Ticket.findById(id) == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        throw new ApiException(503, "AI_UNAVAILABLE",
                "AI summary unavailable. Please write resolution manually.");
    }

    // ---- helpers ---------------------------------------------------------

    private String nextTicketNumber(String tenantId) {
        Object max = Panache.getEntityManager()
                .createNativeQuery("SELECT MAX(CAST(SUBSTR(ticket_number, 5) AS INTEGER)) FROM tickets WHERE tenant_id = ?1")
                .setParameter(1, tenantId)
                .getSingleResult();
        int next = (max == null ? 0 : ((Number) max).intValue()) + 1;
        return String.format("TKT-%05d", next);
    }

    private void recordEvent(String tenantId, String ticketId, String type, String actorType, String actorId) {
        TicketEvent event = new TicketEvent();
        event.id = UUID.randomUUID().toString();
        event.tenantId = tenantId;
        event.ticketId = ticketId;
        event.eventType = type;
        event.actorType = actorType;
        event.actorId = actorId;
        event.persist();
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
