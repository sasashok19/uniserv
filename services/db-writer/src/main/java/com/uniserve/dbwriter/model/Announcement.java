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
import java.util.UUID;

/** {@code announcements} (UI_REVAMP_v2 Feature C) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "announcements")
public class Announcement extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "title", nullable = false)
    public String title;

    @Column(name = "body", nullable = false)
    public String body;

    @Column(name = "created_by", nullable = false)
    public String createdBy;

    @Column(name = "is_active")
    public Integer isActive;

    @Column(name = "expires_at")
    public String expiresAt;

    @Column(name = "created_at")
    public String createdAt;

    @Column(name = "updated_at")
    public String updatedAt;

    @PrePersist
    void prePersist() {
        if (id == null) {
            id = UUID.randomUUID().toString();
        }
        if (isActive == null) {
            isActive = 1;
        }
        String now = SqliteTime.now();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = SqliteTime.now();
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("title", title);
        m.put("body", body);
        m.put("created_by", createdBy);
        m.put("is_active", isActive);
        m.put("expires_at", expiresAt);
        m.put("created_at", createdAt);
        m.put("updated_at", updatedAt);
        return m;
    }
}
