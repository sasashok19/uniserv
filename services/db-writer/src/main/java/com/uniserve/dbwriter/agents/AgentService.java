package com.uniserve.dbwriter.agents;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Agent;
import io.quarkus.hibernate.orm.panache.Panache;
import io.quarkus.panache.common.Sort;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.transaction.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Agent CRUD (Feature 04/11), backed by Hibernate ORM with Panache. api-gateway
 * owns auth/RBAC; this owns the writes. Lookups by email include
 * {@code password_hash} for login verification.
 */
@ApplicationScoped
public class AgentService {

    @Transactional
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
        Agent a = new Agent();
        a.id = strOr(body, "id", UUID.randomUUID().toString());
        a.tenantId = tenantId;
        a.name = name;
        a.email = email;
        a.passwordHash = passwordHash == null ? "" : passwordHash;
        a.role = role;
        a.persistAndFlush();
        return a.toMap();
    }

    public Optional<Map<String, Object>> getById(String id) {
        Agent a = Agent.findById(id);
        return Optional.ofNullable(a).map(Agent::toMap);
    }

    public Optional<Map<String, Object>> findByEmail(String email) {
        return Agent.<Agent>find("email", email).firstResultOptional().map(Agent::toMap);
    }

    public List<Map<String, Object>> list(String tenantId) {
        return Agent.<Agent>find("tenantId", Sort.by("createdAt"), tenantId)
                .list().stream().map(Agent::toMap).toList();
    }

    @Transactional
    public Map<String, Object> update(String id, Map<String, Object> body) {
        Agent a = Agent.findById(id);
        if (a == null) {
            throw new ApiException(404, "NOT_FOUND", "agent not found: " + id);
        }
        if (body.containsKey("name")) {
            a.name = str(body, "name");
        }
        if (body.containsKey("role")) {
            a.role = str(body, "role");
        }
        if (body.containsKey("email")) {
            a.email = str(body, "email");
        }
        if (body.containsKey("isActive")) {
            a.isActive = boolInt(body.get("isActive"));
        }
        if (body.containsKey("passwordHash")) {
            a.passwordHash = str(body, "passwordHash");
        }
        Panache.getEntityManager().flush();
        return a.toMap();
    }

    private static int boolInt(Object v) {
        if (v instanceof Boolean b) {
            return b ? 1 : 0;
        }
        if (v instanceof Number n) {
            return n.intValue();
        }
        return 0;
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
