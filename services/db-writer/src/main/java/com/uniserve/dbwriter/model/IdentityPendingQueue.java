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

/** {@code identity_pending_queue} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "identity_pending_queue")
public class IdentityPendingQueue extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "thread_id", nullable = false)
    public String threadId;

    @Column(name = "channel", nullable = false)
    public String channel;

    @Column(name = "channel_identity_value")
    public String channelIdentityValue;

    @Column(name = "raw_message")
    public String rawMessage;

    @Column(name = "timeout_at", nullable = false)
    public String timeoutAt;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("thread_id", threadId);
        m.put("channel", channel);
        m.put("channel_identity_value", channelIdentityValue);
        m.put("raw_message", rawMessage);
        m.put("timeout_at", timeoutAt);
        m.put("created_at", createdAt);
        return m;
    }
}
