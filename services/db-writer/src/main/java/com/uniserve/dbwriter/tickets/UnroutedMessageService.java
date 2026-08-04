package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Ticket;
import com.uniserve.dbwriter.model.TicketMessage;
import com.uniserve.dbwriter.model.UnroutedMessage;
import io.quarkus.hibernate.orm.panache.Panache;
import io.quarkus.panache.common.Page;
import io.quarkus.panache.common.Sort;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.transaction.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Unrouted citizen messages (Feature 24) — stored when every routing rung has
 * declined and creating a ticket would be wrong.
 *
 * The queue is small by construction: it only receives messages that carry no
 * ticket reference, answer no outstanding question of ours, and do not read as
 * a complaint. If it ever grows large, routing has regressed — which is exactly
 * why these are visible rather than silently dropped.
 */
@ApplicationScoped
public class UnroutedMessageService {

    private static final Set<String> RESOLVABLE_STATUSES =
            Set.of(UnroutedMessage.PENDING, UnroutedMessage.ESCALATED);

    private static final int MAX_PAGE_SIZE = 100;

    @Transactional
    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        String channel = str(body, "channel");
        String content = str(body, "content");
        if (tenantId == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        if (channel == null) {
            throw new ApiException(400, "CHANNEL_REQUIRED", "channel is required");
        }
        if (content == null || content.isBlank()) {
            throw new ApiException(422, "CONTENT_EMPTY", "content is required");
        }

        UnroutedMessage m = new UnroutedMessage();
        m.id = UUID.randomUUID().toString();
        m.tenantId = tenantId;
        m.channel = channel;
        m.channelIdentityValue = str(body, "channelIdentityValue");
        m.content = content;
        m.channelMessageId = str(body, "channelMessageId");
        m.reason = str(body, "reason");
        // `escalated` on arrival is legitimate: ai-core sets it when this
        // contact was already asked to clarify and did not manage to.
        String status = strOr(body, "status", UnroutedMessage.PENDING);
        if (!UnroutedMessage.PENDING.equals(status) && !UnroutedMessage.ESCALATED.equals(status)) {
            throw new ApiException(422, "INVALID_STATUS",
                    "a new unrouted message must be pending or escalated");
        }
        m.status = status;
        m.askCount = intOr(body, "askCount", 0);
        m.persistAndFlush();
        return m.toMap();
    }

    /** Pending/escalated first (that is the work), newest first within a status. */
    public List<Map<String, Object>> list(String tenantId, String status, int page, int pageSize) {
        int size = Math.min(Math.max(pageSize, 1), MAX_PAGE_SIZE);
        String query = status == null || status.isBlank()
                ? "tenantId = ?1"
                : "tenantId = ?1 and status in ?2";
        Object param = status == null || status.isBlank() ? null : List.of(status.split(","));
        var find = param == null
                ? UnroutedMessage.<UnroutedMessage>find(query, Sort.by("createdAt").descending(), tenantId)
                : UnroutedMessage.<UnroutedMessage>find(query, Sort.by("createdAt").descending(), tenantId, param);
        return find.page(Page.of(Math.max(page - 1, 0), size)).list()
                .stream().map(UnroutedMessage::toMap).toList();
    }

    public long count(String tenantId, String status) {
        if (status == null || status.isBlank()) {
            return UnroutedMessage.count("tenantId = ?1", tenantId);
        }
        return UnroutedMessage.count("tenantId = ?1 and status in ?2", tenantId, List.of(status.split(",")));
    }

    /**
     * How many times this contact has already been asked to clarify (Feature 24).
     * ai-core reads this before deciding whether to ask again or escalate, so a
     * citizen who cannot produce a ticket reference is never asked twice.
     */
    public long recentAskCount(String tenantId, String channelIdentityValue, String since) {
        if (channelIdentityValue == null || channelIdentityValue.isBlank()) {
            return 0;
        }
        return UnroutedMessage.count(
                "tenantId = ?1 and channelIdentityValue = ?2 and askCount > 0 and createdAt >= ?3",
                tenantId, channelIdentityValue, since == null ? "" : since);
    }

    /**
     * Attach an unrouted message to the ticket it actually belonged to, copying
     * it onto that ticket's conversation so the citizen's words end up where an
     * agent reading the ticket will see them — filing it without that would
     * only clear the queue, not deliver the message.
     */
    @Transactional
    public Map<String, Object> attach(String id, String ticketId, String agentId) {
        UnroutedMessage m = required(id);
        if (!RESOLVABLE_STATUSES.contains(m.status)) {
            throw new ApiException(422, "ALREADY_RESOLVED",
                    "this message is already " + m.status);
        }
        Ticket t = Ticket.findById(ticketId);
        if (t == null) {
            throw new ApiException(404, "TICKET_NOT_FOUND", "ticket not found: " + ticketId);
        }
        if (!t.tenantId.equals(m.tenantId)) {
            throw new ApiException(422, "TENANT_MISMATCH", "ticket belongs to another tenant");
        }

        TicketMessage copied = new TicketMessage();
        copied.id = UUID.randomUUID().toString();
        copied.tenantId = m.tenantId;
        copied.ticketId = t.id;
        copied.channel = m.channel;
        copied.direction = "inbound";
        copied.authorType = "user";
        copied.content = m.content;
        // Carrying the provider id across means a LATER reply-to pointing at
        // this same message resolves to this ticket by rung 0 — the agent's
        // decision teaches routing, rather than having to be repeated.
        copied.channelMessageId = m.channelMessageId;
        copied.persist();

        m.status = UnroutedMessage.ATTACHED;
        m.resolvedTicketId = t.id;
        m.resolvedBy = agentId;
        Panache.getEntityManager().flush();
        return m.toMap();
    }

    @Transactional
    public Map<String, Object> discard(String id, String agentId) {
        UnroutedMessage m = required(id);
        if (!RESOLVABLE_STATUSES.contains(m.status)) {
            throw new ApiException(422, "ALREADY_RESOLVED", "this message is already " + m.status);
        }
        m.status = UnroutedMessage.DISCARDED;
        m.resolvedBy = agentId;
        Panache.getEntityManager().flush();
        return m.toMap();
    }

    private UnroutedMessage required(String id) {
        UnroutedMessage m = UnroutedMessage.findById(id);
        if (m == null) {
            throw new ApiException(404, "NOT_FOUND", "unrouted message not found: " + id);
        }
        return m;
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static String strOr(Map<String, Object> body, String key, String fallback) {
        String v = str(body, key);
        return v == null ? fallback : v;
    }

    private static int intOr(Map<String, Object> body, String key, int fallback) {
        Object v = body == null ? null : body.get(key);
        return v == null ? fallback : ((Number) v).intValue();
    }
}
