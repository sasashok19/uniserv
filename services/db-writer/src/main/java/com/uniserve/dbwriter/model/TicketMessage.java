package com.uniserve.dbwriter.model;

import com.uniserve.dbwriter.util.SqliteTime;
import io.quarkus.hibernate.orm.panache.PanacheEntityBase;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.util.LinkedHashMap;
import java.util.Map;

/** {@code ticket_messages} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "ticket_messages")
public class TicketMessage extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "ticket_id", nullable = false)
    public String ticketId;

    @Column(name = "channel", nullable = false)
    public String channel;

    @Column(name = "direction", nullable = false)
    public String direction;

    @Column(name = "author_type", nullable = false)
    public String authorType;

    @Column(name = "author_id")
    public String authorId;

    @Column(name = "author_label")
    public String authorLabel;

    @Column(name = "content")
    public String content;

    @Column(name = "media_urls_json")
    public String mediaUrlsJson;

    @Column(name = "is_ai_generated")
    public Integer isAiGenerated;

    /** The id the CHANNEL PROVIDER gave this message (Feature 24) — a WhatsApp
     * wamid or an email Message-ID. Set on outbound messages after a successful
     * send, and on inbound messages from the webhook/poller. It is what lets an
     * inbound reply-to (`context.id` / `In-Reply-To`) resolve to the exact
     * ticket the citizen is replying on, with no heuristic involved. */
    @Column(name = "channel_message_id")
    public String channelMessageId;

    /** 1 when this outbound message ASKED the citizen for identity/intake
     * details (Feature 24). A bare "yes" is structurally identical whether it
     * answers "did you mean x@gmail.com?" or "is this resolved?", so the intake
     * guard may only claim such a message when the last thing we asked on that
     * stub was in fact an intake question. */
    @Column(name = "is_intake_request")
    public Integer isIntakeRequest;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
        if (mediaUrlsJson == null) {
            mediaUrlsJson = "[]";
        }
        if (isAiGenerated == null) {
            isAiGenerated = 0;
        }
        if (isIntakeRequest == null) {
            isIntakeRequest = 0;
        }
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("ticket_id", ticketId);
        m.put("channel", channel);
        m.put("direction", direction);
        m.put("author_type", authorType);
        m.put("author_id", authorId);
        m.put("author_label", authorLabel);
        m.put("content", content);
        m.put("media_urls_json", mediaUrlsJson);
        m.put("is_ai_generated", isAiGenerated);
        m.put("channel_message_id", channelMessageId);
        m.put("is_intake_request", isIntakeRequest);
        m.put("created_at", createdAt);
        return m;
    }
}
