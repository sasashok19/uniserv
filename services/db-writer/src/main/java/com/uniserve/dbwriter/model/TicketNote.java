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

/**
 * {@code ticket_notes} (Feature 05) — Hibernate Panache active-record entity.
 * The 20-char mandatory-note rule for status transitions is enforced in
 * {@code TicketService}, not here (this entity only carries the DB-level
 * {@code length >= 1} minimum).
 */
@Entity
@Table(name = "ticket_notes")
public class TicketNote extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "ticket_id", nullable = false)
    public String ticketId;

    @Column(name = "agent_id", nullable = false)
    public String agentId;

    @Column(name = "content", nullable = false)
    public String content;

    @Column(name = "is_mandatory")
    public Integer isMandatory;

    @Column(name = "transition_from")
    public String transitionFrom;

    @Column(name = "transition_to")
    public String transitionTo;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
        if (isMandatory == null) {
            isMandatory = 0;
        }
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("ticket_id", ticketId);
        m.put("agent_id", agentId);
        m.put("content", content);
        m.put("is_mandatory", isMandatory);
        m.put("transition_from", transitionFrom);
        m.put("transition_to", transitionTo);
        m.put("created_at", createdAt);
        return m;
    }
}
