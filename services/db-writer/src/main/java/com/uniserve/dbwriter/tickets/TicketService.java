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
import jakarta.persistence.Tuple;
import jakarta.transaction.Transactional;

import java.util.ArrayList;
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

    /**
     * Feature 21: cancelling is mandatory-note from EVERY source status, so it
     * is checked by destination rather than listed as one pair per origin.
     * A cancelled ticket leaves the backlog with no resolution recorded
     * against it — the note is the only account of why, and it is exactly the
     * action an audit will ask about.
     */
    private static final String CANCELLED = "cancelled";

    /** Statuses a ticket cannot be cancelled FROM (already terminal). */
    private static final Set<String> TERMINAL_STATUSES = Set.of("closed", CANCELLED);

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
        t.originMessageId = str(body, "originMessageId");
        t.isDuplicate = intOr(body, "isDuplicate", 0);
        t.parentTicketId = str(body, "parentTicketId");
        t.serviceId = str(body, "serviceId");
        t.chiefComplaint = str(body, "chiefComplaint");
        t.slaDueAt = str(body, "slaDueAt");
        // Feature 26: normally NULL at creation — the ETA is the agent's promise,
        // made on the first transition. Accepted here only so a caller that
        // genuinely knows it up front (an import, a test fixture) isn't forced to
        // create-then-patch.
        t.etaAt = TicketEta.normalise(body.get("eta"));
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

    /**
     * Queue list (Feature 12), backed by a native SQL query that LEFT JOINs
     * {@code identity_profiles} so each row carries the citizen's
     * name/email/phone (for the dashboard's Name/Email/Mobile columns) and can
     * be sorted by ANY column — including those citizen fields — server-side,
     * across the whole result set rather than just the current page. Panache's
     * active-record queries can't express the join (a ticket references its
     * identity by the free `identity_id` string, not a mapped association), so
     * this drops to native SQL. {@code sortBy} is whitelisted via
     * {@link #SORT_COLUMNS} (never interpolated raw) to keep it injection-safe.
     */
    public List<Map<String, Object>> list(String tenantId, String status, String assignedTo,
                                          String channel, String category, String identityId,
                                          String identityStatus, String threadId, String ticketNumber,
                                          String originMessageId, boolean includeArchived, int page, int pageSize,
                                          String sortBy, String sortDir) {
        Map<String, Object> params = new HashMap<>();
        String where = buildWhere(tenantId, status, assignedTo, channel, category, identityId,
                identityStatus, threadId, ticketNumber, originMessageId, includeArchived, params);
        // NOTE: SORT_COLUMNS is an immutable Map.ofEntries map — get(null) throws
        // NPE, so guard the null (callers without an explicit sortBy: ai-core's
        // thread-id stub lookups, older dashboard sessions).
        String sortCol = sortBy == null ? "t.created_at" : SORT_COLUMNS.getOrDefault(sortBy, "t.created_at");
        String dir = "asc".equalsIgnoreCase(sortDir) ? "asc" : "desc";
        int size = Math.min(Math.max(pageSize, 1), 100);

        String sql = "select " + String.join(", ", listSelectColumns()) + ", "
                + "ip.name as citizen_name, ip.email as citizen_email, ip.phone as citizen_phone "
                + "from tickets t "
                + "left join identity_profiles ip on ip.master_id = t.identity_id and ip.tenant_id = t.tenant_id "
                + "where " + where
                // Stable, deterministic ordering: primary sort, then newest ticket as tiebreaker.
                + " order by " + sortCol + " " + dir + ", t.ticket_number desc "
                + "limit :limit offset :offset";

        var q = Panache.getEntityManager().createNativeQuery(sql, Tuple.class);
        params.forEach(q::setParameter);
        q.setParameter("limit", size);
        q.setParameter("offset", Math.max(page - 1, 0) * size);

        List<String> cols = new ArrayList<>(LIST_COLUMNS);
        cols.add("citizen_name");
        cols.add("citizen_email");
        cols.add("citizen_phone");
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object rowObj : q.getResultList()) {
            Tuple row = (Tuple) rowObj;
            Map<String, Object> m = new LinkedHashMap<>();
            for (String c : cols) {
                m.put(c, row.get(c));
            }
            out.add(m);
        }
        return out;
    }

    /** Full count of tickets matching the same filters (for pagination). */
    public long count(String tenantId, String status, String assignedTo, String channel, String category,
                      String identityId, String identityStatus, String threadId, String ticketNumber,
                      String originMessageId, boolean includeArchived) {
        Map<String, Object> params = new HashMap<>();
        String where = buildWhere(tenantId, status, assignedTo, channel, category, identityId,
                identityStatus, threadId, ticketNumber, originMessageId, includeArchived, params);
        var q = Panache.getEntityManager().createNativeQuery("select count(*) from tickets t where " + where);
        params.forEach(q::setParameter);
        return ((Number) q.getSingleResult()).longValue();
    }

    /** API sort key -> SQL column, whitelisted so {@code sortBy} is never interpolated raw. */
    private static final Map<String, String> SORT_COLUMNS = Map.ofEntries(
            Map.entry("ticketNumber", "t.ticket_number"),
            Map.entry("createdAt", "t.created_at"),
            Map.entry("status", "t.status"),
            Map.entry("category", "t.category"),
            Map.entry("priorityScore", "t.priority_score"),
            Map.entry("priorityLabel", "t.priority_label"),
            Map.entry("channel", "t.channel_origin"),
            Map.entry("chiefComplaint", "t.chief_complaint"),
            Map.entry("etaAt", "t.eta_at"),
            Map.entry("identityStatus", "t.identity_status"),
            Map.entry("citizenName", "ip.name"),
            Map.entry("citizenEmail", "ip.email"),
            Map.entry("citizenPhone", "ip.phone"));

    /** Ticket columns returned by the list query (snake_case, matching {@link Ticket#toMap}). */
    private static final List<String> LIST_COLUMNS = List.of(
            "id", "ticket_number", "status", "category", "subcategory", "priority_score",
            "priority_label", "sentiment_score", "channel_origin", "assigned_to", "identity_id",
            "identity_status", "identity_source", "thread_id", "origin_message_id", "is_duplicate",
            "parent_ticket_id", "service_id", "chief_complaint", "resolution", "sla_due_at",
            "eta_at", "first_transition_at",
            "resolved_at", "closed_at", "reopened_count", "reopened_by", "created_at", "updated_at");

    private static List<String> listSelectColumns() {
        List<String> cols = new ArrayList<>();
        for (String c : LIST_COLUMNS) {
            cols.add("t." + c);
        }
        return cols;
    }

    /** Shared native-SQL WHERE clause (alias {@code t}); fills {@code params}.
     * Package-private (not {@code private}) so {@link TicketServiceTest} can
     * exercise it directly, pure-function style, without a live database. */
    static String buildWhere(String tenantId, String status, String assignedTo, String channel,
                                     String category, String identityId, String identityStatus,
                                     String threadId, String ticketNumber, String originMessageId,
                                     boolean includeArchived, Map<String, Object> params) {
        StringBuilder w = new StringBuilder("t.tenant_id = :tenantId");
        params.put("tenantId", tenantId);
        if (status != null && !status.isBlank()) {
            w.append(" and t.status in (:statuses)");
            params.put("statuses", List.of(status.split(",")));
        }
        if (assignedTo != null && !assignedTo.isBlank()) {
            w.append(" and t.assigned_to = :assignedTo");
            params.put("assignedTo", assignedTo);
        }
        if (identityId != null && !identityId.isBlank()) {
            w.append(" and t.identity_id = :identityId");
            params.put("identityId", identityId);
        }
        if (identityStatus != null && !identityStatus.isBlank()) {
            w.append(" and t.identity_status in (:identityStatuses)");
            params.put("identityStatuses", List.of(identityStatus.split(",")));
        }
        if (threadId != null && !threadId.isBlank()) {
            w.append(" and t.thread_id = :threadId");
            params.put("threadId", threadId);
        }
        if (ticketNumber != null && !ticketNumber.isBlank()) {
            w.append(" and t.ticket_number = :ticketNumber");
            params.put("ticketNumber", ticketNumber);
        }
        if (originMessageId != null && !originMessageId.isBlank()) {
            // Feature 19: lets a citizen's WhatsApp swipe-reply (Meta's
            // context.id, the wamid of the message they replied to) or an
            // email's In-Reply-To header resolve straight to the ticket that
            // message originated from — the most explicit continuation
            // signal available, stronger than free-text ticket-number
            // parsing or identity/topic heuristics. See
            // ai-core's app/tickets/intake.py ensure_ticket_stub.
            w.append(" and t.origin_message_id = :originMessageId");
            params.put("originMessageId", originMessageId);
        }
        if (channel != null && !channel.isBlank()) {
            w.append(" and t.channel_origin = :channel");
            params.put("channel", channel);
        }
        if (category != null && !category.isBlank()) {
            w.append(" and t.category = :category");
            params.put("category", category);
        }
        if (!includeArchived) {
            w.append(" and t.archived_at is null");
        }
        return w.toString();
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
            String newAssignee = str(body, "assignedTo");
            // Audit assignment changes (dashboard's ticket-detail Audit section).
            // actorAgentId is optional metadata from the gateway (who did it);
            // meta_json records who it went TO (null = unassigned).
            if (!java.util.Objects.equals(t.assignedTo, newAssignee)) {
                TicketEvent event = new TicketEvent();
                event.id = UUID.randomUUID().toString();
                event.tenantId = t.tenantId;
                event.ticketId = t.id;
                event.eventType = newAssignee == null ? "ticket.unassigned" : "ticket.assigned";
                event.actorType = str(body, "actorAgentId") == null ? "system" : "agent";
                event.actorId = str(body, "actorAgentId");
                event.metaJson = newAssignee == null ? null : "{\"assignedTo\":\"" + newAssignee + "\"}";
                event.persist();
            }
            t.assignedTo = newAssignee;
        }
        if (body.containsKey("resolution")) {
            t.resolution = str(body, "resolution");
        }
        if (body.containsKey("slaDueAt")) {
            t.slaDueAt = str(body, "slaDueAt");
        }
        if (body.containsKey("eta")) {
            // Revising an ETA later is a normal, expected act (the part arrived
            // early; the crew got pulled to an outage). It is audited rather
            // than blocked — see the ticket.eta_changed event below.
            String newEta = TicketEta.normalise(body.get("eta"));
            if (!java.util.Objects.equals(t.etaAt, newEta)) {
                TicketEvent event = new TicketEvent();
                event.id = UUID.randomUUID().toString();
                event.tenantId = t.tenantId;
                event.ticketId = t.id;
                event.eventType = "ticket.eta_changed";
                event.actorType = str(body, "actorAgentId") == null ? "system" : "agent";
                event.actorId = str(body, "actorAgentId");
                event.metaJson = "{\"from\":" + jsonOrNull(t.etaAt) + ",\"to\":" + jsonOrNull(newEta) + "}";
                event.persist();
            }
            t.etaAt = newEta;
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
        if (body.containsKey("chiefComplaint")) {
            t.chiefComplaint = str(body, "chiefComplaint");
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

        if (CANCELLED.equals(toStatus) && TERMINAL_STATUSES.contains(fromStatus)) {
            throw new ApiException(422, "ALREADY_TERMINAL",
                    "Cannot cancel a ticket that is already " + fromStatus);
        }

        if (MANDATORY_NOTE_TRANSITIONS.contains(transitionKey) || CANCELLED.equals(toStatus)) {
            if (noteContent == null || noteContent.trim().length() < 20) {
                throw new ApiException(422, "NOTE_TOO_SHORT",
                        "Note must be at least 20 characters for " + transitionKey + " transition");
            }
        }

        // Feature 26: an ETA is mandatory as part of the FIRST transition.
        //
        // "First" is `first_transition_at is null`, not `status == 'open'`: a
        // ticket can reach a non-open status through the unvalidated PATCH path
        // (ai-core closes a confirmed duplicate that way), and that must not
        // count as having been picked up by an agent, nor silently excuse the
        // ETA forever after.
        //
        // Cancelling is exempt. An ETA is a promise about work that will happen,
        // and cancelling is the declaration that it will not — demanding a
        // completion date in order to say "we are not doing this" is nonsense,
        // and the mandatory note already covers the audit question.
        boolean firstTransition = t.firstTransitionAt == null;
        String suppliedEta = TicketEta.normalise(body.get("eta"));
        if (suppliedEta != null) {
            t.etaAt = suppliedEta;
        }
        if (firstTransition && !CANCELLED.equals(toStatus) && t.etaAt == null) {
            throw new ApiException(422, "ETA_REQUIRED",
                    "An ETA is required on the first transition of a ticket. "
                            + "Supply `eta` as a date (yyyy-MM-dd) or timestamp (yyyy-MM-dd HH:mm:ss).");
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
        } else if (CANCELLED.equals(toStatus)) {
            // Terminal like closed, so closed_at is stamped (queue/SLA queries
            // already key off it) — but resolved_at is deliberately left NULL.
            // A cancelled ticket was never resolved, and letting it count as
            // one would quietly inflate resolution rate and skew MTTR.
            t.closedAt = SqliteTime.now();
            t.resolvedAt = null;
        } else if ("reopened".equals(toStatus)) {
            // Clear resolution, bump counter, record who reopened — assignee preserved.
            t.resolution = null;
            t.resolvedAt = null;
            t.closedAt = null;
            t.reopenedCount = (t.reopenedCount == null ? 0 : t.reopenedCount) + 1;
            t.reopenedBy = agentId;
        }

        // Stamped after every check has passed, so a rejected transition (short
        // note, missing ETA) does not burn the one chance to demand an ETA.
        if (firstTransition) {
            t.firstTransitionAt = SqliteTime.now();
        }

        recordEvent(t.tenantId, t.id, "status." + toStatus, agentId == null ? "system" : "agent", agentId);
        cache.invalidate(id);
        Panache.getEntityManager().flush();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", toStatus);
        result.put("resolvedAt", t.resolvedAt);
        result.put("etaAt", t.etaAt);
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
        // Feature 24: the provider's own id for this message, when the caller
        // already has it (inbound). Outbound sends only learn it from the send
        // response, so those come back through `setMessageChannelId` instead.
        msg.channelMessageId = str(body, "channelMessageId");
        msg.isIntakeRequest = intOr(body, "isIntakeRequest", 0);
        msg.persistAndFlush();
        return msg.toMap();
    }

    /**
     * Record the provider id of a message we have just sent (Feature 24).
     *
     * Separate from {@link #addMessage} because of the order forced by the
     * channel: the message row must exist BEFORE the send (so a failed send
     * still leaves a record of what we tried to say), but the wamid/Message-ID
     * only exists AFTER it. One narrow setter rather than a general message
     * PATCH — nothing else about a sent message may be rewritten.
     */
    @Transactional
    public Map<String, Object> setMessageChannelId(String messageId, String channelMessageId) {
        TicketMessage msg = TicketMessage.findById(messageId);
        if (msg == null) {
            throw new ApiException(404, "NOT_FOUND", "message not found: " + messageId);
        }
        if (channelMessageId == null || channelMessageId.isBlank()) {
            throw new ApiException(422, "CHANNEL_MESSAGE_ID_REQUIRED", "channelMessageId is required");
        }
        msg.channelMessageId = channelMessageId;
        Panache.getEntityManager().flush();
        return msg.toMap();
    }

    /**
     * The message a provider id belongs to (Feature 24) — the lookup behind
     * routing rung 0. An inbound reply names the message it replies to; this
     * turns that into the ticket it happened on, exactly, with no heuristic.
     *
     * Tenant-scoped: provider ids are globally unique in practice, but a lookup
     * that could cross tenants has no business existing in a multi-tenant table.
     */
    public Optional<Map<String, Object>> findByChannelMessageId(String tenantId, String channelMessageId) {
        if (channelMessageId == null || channelMessageId.isBlank()) {
            return Optional.empty();
        }
        return TicketMessage.<TicketMessage>find(
                        "tenantId = ?1 and channelMessageId = ?2", tenantId, channelMessageId)
                .firstResultOptional().map(TicketMessage::toMap);
    }

    // NOTE: there is deliberately no "last outbound message" endpoint. Routing
    // needs BOTH a candidate ticket's original complaint and the last thing we
    // asked on it, and `messages(id)` already returns the whole timeline in one
    // round trip — a dedicated endpoint would double the calls per candidate to
    // save nothing. See ai-core's `_ticket_dialogue`.

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

    /** Allowed `actor_type` values — mirrors the ticket_events CHECK constraint. */
    private static final Set<String> EVENT_ACTOR_TYPES = Set.of("system", "ai", "agent");

    /**
     * Append an audit-trail entry supplied by another service (Feature 22).
     * Validated here rather than trusted: a bad `actorType` would otherwise
     * fail deep in the CHECK constraint as an opaque 500.
     */
    @Transactional
    public Map<String, Object> addEvent(String id, Map<String, Object> body) {
        Ticket t = Ticket.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        String eventType = str(body, "eventType");
        if (eventType == null || eventType.isBlank()) {
            throw new ApiException(422, "EVENT_TYPE_REQUIRED", "eventType is required");
        }
        String actorType = strOr(body, "actorType", "system");
        if (!EVENT_ACTOR_TYPES.contains(actorType)) {
            throw new ApiException(422, "INVALID_ACTOR_TYPE",
                    "actorType must be one of " + EVENT_ACTOR_TYPES);
        }
        TicketEvent event = new TicketEvent();
        event.id = UUID.randomUUID().toString();
        event.tenantId = t.tenantId;
        event.ticketId = t.id;
        event.eventType = eventType;
        event.actorType = actorType;
        event.actorId = str(body, "actorId");
        // Small structured payload (e.g. which ticket a duplicate points at) —
        // stored as-is in the existing meta_json column, no schema change.
        Object meta = body.get("meta");
        if (meta instanceof Map<?, ?> metaMap && !metaMap.isEmpty()) {
            try {
                event.metaJson = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(metaMap);
            } catch (Exception e) {
                throw new ApiException(422, "INVALID_META", "meta must be a JSON object");
            }
        }
        event.persistAndFlush();
        return event.toMap();
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

    /** A JSON string literal, or the bare token {@code null}. Both ETA values in
     * an eta_changed event are optional (the first ever ETA has no `from`), and
     * {@code "null"} quoted as a string would read back as the text "null". */
    private static String jsonOrNull(String value) {
        return value == null ? "null" : "\"" + value.replace("\"", "\\\"") + "\"";
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
