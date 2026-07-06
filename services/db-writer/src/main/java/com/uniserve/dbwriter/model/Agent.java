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

/** {@code agents} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "agents")
public class Agent extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "name", nullable = false)
    public String name;

    @Column(name = "email", nullable = false)
    public String email;

    @Column(name = "password_hash", nullable = false)
    public String passwordHash;

    @Column(name = "role", nullable = false)
    public String role;

    // 0/1 (SQLite has no native BOOLEAN); kept Integer to match the historical
    // plain-JDBC wire shape that other services (api-gateway) already parse.
    @Column(name = "is_active")
    public Integer isActive;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
        if (isActive == null) {
            isActive = 1;
        }
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("tenant_id", tenantId);
        m.put("name", name);
        m.put("email", email);
        m.put("password_hash", passwordHash);
        m.put("role", role);
        m.put("is_active", isActive);
        m.put("created_at", createdAt);
        return m;
    }
}
