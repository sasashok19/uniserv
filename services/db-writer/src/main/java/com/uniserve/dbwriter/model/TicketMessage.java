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
        m.put("created_at", createdAt);
        return m;
    }
}
