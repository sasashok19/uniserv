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

/** {@code identity_profiles} (Feature 05) — Hibernate Panache active-record entity. */
@Entity
@Table(name = "identity_profiles")
public class IdentityProfile extends PanacheEntityBase {

    @Id
    @Column(name = "id")
    public String id;

    @Column(name = "tenant_id", nullable = false)
    public String tenantId;

    @Column(name = "master_id", nullable = false, unique = true)
    public String masterId;

    @Column(name = "name")
    public String name;

    @Column(name = "email")
    public String email;

    @Column(name = "phone")
    public String phone;

    @Column(name = "channel_ids_json")
    public String channelIdsJson;

    @Column(name = "is_anonymous")
    public Integer isAnonymous;

    @Column(name = "anon_ref_id", unique = true)
    public String anonRefId;

    @Column(name = "merged_into")
    public String mergedInto;

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
        if (channelIdsJson == null) {
            channelIdsJson = "[]";
        }
        if (isAnonymous == null) {
            isAnonymous = 0;
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
        m.put("master_id", masterId);
        m.put("name", name);
        m.put("email", email);
        m.put("phone", phone);
        m.put("channel_ids_json", channelIdsJson);
        m.put("is_anonymous", isAnonymous);
        m.put("anon_ref_id", anonRefId);
        m.put("merged_into", mergedInto);
        m.put("created_at", createdAt);
        m.put("updated_at", updatedAt);
        return m;
    }
}
