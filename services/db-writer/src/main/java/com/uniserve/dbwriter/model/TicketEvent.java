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

/** {@code ticket_events} audit trail (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "ticket_events")
public class TicketEvent extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "ticket_id", nullable = false)
    public String ticketId;

    @Column(name = "event_type", nullable = false)
    public String eventType;

    @Column(name = "actor_type", nullable = false)
    public String actorType;

    @Column(name = "actor_id")
    public String actorId;

    @Column(name = "meta_json")
    public String metaJson;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
        if (metaJson == null) {
            metaJson = "{}";
        }
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("ticket_id", ticketId);
        m.put("event_type", eventType);
        m.put("actor_type", actorType);
        m.put("actor_id", actorId);
        m.put("meta_json", metaJson);
        m.put("created_at", createdAt);
        return m;
    }
}
