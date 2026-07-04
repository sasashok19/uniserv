package com.uniserve.dbwriter.agents;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.db.Db;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Agent CRUD (Feature 04/11). api-gateway owns auth/RBAC; this owns the writes.
 * Lookups by email include {@code password_hash} for login verification.
 */
@ApplicationScoped
public class AgentService {

    @Inject
    Db db;

    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        String name = str(body, "name");
        String email = str(body, "email");
        String role = str(body, "role");
        String passwordHash = str(body, "passwordHash");
        if (tenantId == null || name == null || email == null || role == null) {
            throw new ApiException(400, "AGENT_FIELDS_REQUIRED",
                    "tenantId, name, email and role are required");
        }
        String id = strOr(body, "id", UUID.randomUUID().toString());
        db.update("""
                INSERT INTO agents (id, tenant_id, name, email, password_hash, role, is_active)
                VALUES (?,?,?,?,?,?,1)
                """, id, tenantId, name, email, passwordHash == null ? "" : passwordHash, role);
        return getById(id).orElseThrow();
    }

    public Optional<Map<String, Object>> getById(String id) {
        return db.queryOne("SELECT * FROM agents WHERE id = ?", id);
    }

    public Optional<Map<String, Object>> findByEmail(String email) {
        return db.queryOne("SELECT * FROM agents WHERE email = ?", email);
    }

    public List<Map<String, Object>> list(String tenantId) {
        return db.query("SELECT * FROM agents WHERE tenant_id = ? ORDER BY created_at", tenantId);
    }

    public Map<String, Object> update(String id, Map<String, Object> body) {
        getById(id).orElseThrow(() -> new ApiException(404, "NOT_FOUND", "agent not found: " + id));
        Map<String, String> updatable = Map.of(
                "name", "name", "role", "role", "email", "email",
                "isActive", "is_active", "passwordHash", "password_hash");
        for (Map.Entry<String, String> e : updatable.entrySet()) {
            if (body.containsKey(e.getKey())) {
                Object value = body.get(e.getKey());
                if ("is_active".equals(e.getValue()) && value instanceof Boolean b) {
                    value = b ? 1 : 0;
                }
                db.update("UPDATE agents SET " + e.getValue() + " = ? WHERE id = ?", value, id);
            }
        }
        return getById(id).orElseThrow();
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static String strOr(Map<String, Object> body, String key, String fallback) {
        String v = str(body, key);
        return v == null ? fallback : v;
    }
}
