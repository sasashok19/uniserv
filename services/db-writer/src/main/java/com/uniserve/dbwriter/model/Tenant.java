package com.uniserve.dbwriter.model;

import io.quarkus.hibernate.orm.panache.PanacheEntityBase;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.util.LinkedHashMap;
import java.util.Map;

import com.uniserve.dbwriter.util.SqliteTime;

/** {@code tenants} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "tenants")
public class Tenant extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "name", nullable = false)
    public String name;

    @Column(name = "slug", nullable = false, unique = true)
    public String slug;

    @Column(name = "deployment_mode")
    public String deploymentMode;

    @Column(name = "llm_provider")
    public String llmProvider;

    @Column(name = "config_json")
    public String configJson;

    @Column(name = "created_at")
    public String createdAt;

    @PrePersist
    void prePersist() {
        if (createdAt == null) {
            createdAt = SqliteTime.now();
        }
        if (deploymentMode == null) {
            deploymentMode = "cloud";
        }
        if (llmProvider == null) {
            llmProvider = "anthropic";
        }
        if (configJson == null) {
            configJson = "{}";
        }
    }

    /** Matches the wire shape of the previous plain-JDBC row map (snake_case keys). */
    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("name", name);
        m.put("slug", slug);
        m.put("deployment_mode", deploymentMode);
        m.put("llm_provider", llmProvider);
        m.put("config_json", configJson);
        m.put("created_at", createdAt);
        return m;
    }
}
