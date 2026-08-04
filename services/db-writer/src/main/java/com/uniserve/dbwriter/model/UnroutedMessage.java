package com.uniserve.dbwriter.model;

import com.uniserve.dbwriter.util.SqliteTime;
import io.quarkus.hibernate.orm.panache.PanacheEntityBase;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * {@code unrouted_messages} (Feature 24) — a citizen message that could not be
 * attributed to any ticket and must not invent one.
 *
 * Reached only after every routing rung has declined: no reply-to match, no
 * ticket reference, nothing our outstanding questions explain, and the text
 * itself is not a complaint ("yes", "ok", "you are correct"). The message is
 * kept because a citizen's words disappearing is worse than a misroute — an
 * agent can fix a misroute, but nobody can fix what was never stored.
 */
@Entity
@Table(name = "unrouted_messages")
public class UnroutedMessage extends PanacheEntityBase {

    public static final String PENDING = "pending";
    public static final String ESCALATED = "escalated";
    public static final String ATTACHED = "attached";
    public static final String DISCARDED = "discarded";

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "channel", nullable = false)
    public String channel;

    /** The citizen's channel address. Deliberately not a resolved identity:
     * routing may have failed precisely because identity never resolved. */
    @Column(name = "channel_identity_value")
    public String channelIdentityValue;

    @Column(name = "content", nullable = false)
    public String content;

    @Column(name = "channel_message_id")
    public String channelMessageId;

    /** Why routing gave up, in words an agent can act on. */
    @Column(name = "reason")
    public String reason;

    @Column(name = "status", nullable = false)
    public String status;

    @Column(name = "resolved_ticket_id")
    public String resolvedTicketId;

    @Column(name = "resolved_by")
    public String resolvedBy;

    /** How many times this contact has been asked to clarify. The second
     * unroutable message escalates rather than asking again, so a citizen who
     * answers "I don't have it" never loops. */
    @Column(name = "ask_count", nullable = false)
    public Integer askCount;

    @Column(name = "created_at")
    public String createdAt;

    @Column(name = "updated_at")
    public String updatedAt;

    @PrePersist
    void prePersist() {
        String now = SqliteTime.now();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
        if (status == null) {
            status = PENDING;
        }
        if (askCount == null) {
            askCount = 0;
        }
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = SqliteTime.now();
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("channel", channel);
        m.put("channel_identity_value", channelIdentityValue);
        m.put("content", content);
        m.put("channel_message_id", channelMessageId);
        m.put("reason", reason);
        m.put("status", status);
        m.put("resolved_ticket_id", resolvedTicketId);
        m.put("resolved_by", resolvedBy);
        m.put("ask_count", askCount);
        m.put("created_at", createdAt);
        m.put("updated_at", updatedAt);
        return m;
    }
}
