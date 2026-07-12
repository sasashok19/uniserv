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

/** {@code tickets} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "tickets")
public class Ticket extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "ticket_number", nullable = false)
    public String ticketNumber;

    @Column(name = "identity_id")
    public String identityId;

    @Column(name = "identity_status")
    public String identityStatus;

    @Column(name = "identity_source")
    public String identitySource;

    @Column(name = "assigned_to")
    public String assignedTo;

    @Column(name = "status")
    public String status;

    @Column(name = "category")
    public String category;

    @Column(name = "subcategory")
    public String subcategory;

    @Column(name = "priority_score")
    public Double priorityScore;

    @Column(name = "priority_label")
    public String priorityLabel;

    @Column(name = "sentiment_score")
    public Double sentimentScore;

    @Column(name = "channel_origin", nullable = false)
    public String channelOrigin;

    /** Conversation thread key (Feature 06) — lets ai-core find the same
     * ticket across turns without relying on short-lived Valkey state. */
    @Column(name = "thread_id")
    public String threadId;

    /** Soft-delete (Feature 12): non-null hides the ticket from every queue.
     * Never physically removed. */
    @Column(name = "archived_at")
    public String archivedAt;

    @Column(name = "is_duplicate")
    public Integer isDuplicate;

    @Column(name = "parent_ticket_id")
    public String parentTicketId;

    /** Service/Customer ID (Feature 12/15) — captured from the citizen's
     * intake reply; previously only ever embedded as text in the first message. */
    @Column(name = "service_id")
    public String serviceId;

    @Column(name = "resolution")
    public String resolution;

    @Column(name = "sla_due_at")
    public String slaDueAt;

    @Column(name = "resolved_at")
    public String resolvedAt;

    @Column(name = "closed_at")
    public String closedAt;

    @Column(name = "reopened_count")
    public Integer reopenedCount;

    @Column(name = "reopened_by")
    public String reopenedBy;

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
        if (identityStatus == null) {
            identityStatus = "pending";
        }
        if (status == null) {
            status = "open";
        }
        if (isDuplicate == null) {
            isDuplicate = 0;
        }
        if (reopenedCount == null) {
            reopenedCount = 0;
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
        m.put("ticket_number", ticketNumber);
        m.put("identity_id", identityId);
        m.put("identity_status", identityStatus);
        m.put("identity_source", identitySource);
        m.put("assigned_to", assignedTo);
        m.put("status", status);
        m.put("category", category);
        m.put("subcategory", subcategory);
        m.put("priority_score", priorityScore);
        m.put("priority_label", priorityLabel);
        m.put("sentiment_score", sentimentScore);
        m.put("channel_origin", channelOrigin);
        m.put("thread_id", threadId);
        m.put("archived_at", archivedAt);
        m.put("is_duplicate", isDuplicate);
        m.put("parent_ticket_id", parentTicketId);
        m.put("service_id", serviceId);
        m.put("resolution", resolution);
        m.put("sla_due_at", slaDueAt);
        m.put("resolved_at", resolvedAt);
        m.put("closed_at", closedAt);
        m.put("reopened_count", reopenedCount);
        m.put("reopened_by", reopenedBy);
        m.put("created_at", createdAt);
        m.put("updated_at", updatedAt);
        return m;
    }
}
