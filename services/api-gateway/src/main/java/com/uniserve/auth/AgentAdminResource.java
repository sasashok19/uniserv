package com.uniserve.auth;

import io.quarkus.elytron.security.common.BcryptUtil;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PATCH;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Agent management (Feature 11) — Admin only. Proxies to db-writer. */
@Path("/api/v1/agents")
@Produces(MediaType.APPLICATION_JSON)
public class AgentAdminResource {

    private static final Set<String> VALID_ROLES = Set.of("admin", "lead", "agent");
    private static final Pattern EMAIL_RE = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        String name = strOf(body.get("name"));
        String email = strOf(body.get("email"));
        String role = strOf(body.get("role"));
        String password = strOf(body.get("password"));

        Response invalid = validateFields(name, email, role, password, true);
        if (invalid != null) {
            return invalid;
        }

        Map<String, Object> existing = db.call("GET",
                "/api/v1/db/agents?tenantId=" + user.tenantId() + "&email=" + email, null).body();
        Object existingData = existing.get("data");
        if (existingData instanceof List<?> list && !list.isEmpty()) {
            return Response.status(409).entity(Map.of("error", Map.of(
                    "code", "EMAIL_EXISTS", "message", "An agent with this email already exists"))).build();
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("tenantId", user.tenantId());
        payload.put("name", name);
        payload.put("email", email);
        payload.put("role", role);
        payload.put("passwordHash", BcryptUtil.bcryptHash(password));

        Map<String, Object> created = db.createAgent(payload);
        return Response.status(Response.Status.CREATED).entity(Map.of(
                "id", created.get("id"),
                "name", created.get("name"),
                "role", created.get("role"),
                "isActive", true)).build();
    }

    @GET
    public Response list() {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        List<Map<String, Object>> agents = new ArrayList<>();
        for (Map<String, Object> a : db.listAgents(user.tenantId())) {
            a.remove("password_hash");
            agents.add(a);
        }
        return Response.ok(Map.of("agents", agents)).build();
    }

    /** Name/role/active only — email is the agent's immutable key. */
    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(@PathParam("id") String id, Map<String, Object> body) {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        if (body.containsKey("email")) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "EMAIL_IMMUTABLE", "message", "An agent's email cannot be changed"))).build();
        }
        Map<String, Object> patch = new LinkedHashMap<>();
        if (body.containsKey("name")) {
            String name = strOf(body.get("name"));
            if (name == null || name.isBlank()) {
                return Response.status(422).entity(Map.of("error", Map.of(
                        "code", "NAME_REQUIRED", "message", "Name cannot be empty"))).build();
            }
            patch.put("name", name);
        }
        if (body.containsKey("role")) {
            String role = strOf(body.get("role"));
            if (role == null || !VALID_ROLES.contains(role)) {
                return Response.status(422).entity(Map.of("error", Map.of(
                        "code", "ROLE_INVALID", "message", "Role must be one of admin, lead, agent"))).build();
            }
            patch.put("role", role);
        }
        if (body.containsKey("isActive")) {
            Object active = body.get("isActive");
            patch.put("isActive", (active instanceof Boolean b && b) || "1".equals(String.valueOf(active)) ? 1 : 0);
        }
        Map<String, Object> updated = db.updateAgent(id, patch);
        updated.remove("password_hash");
        return Response.ok(updated).build();
    }

    /** Admin sets a new password directly for a team member (no reset-link flow). */
    @PATCH
    @Path("/{id}/password")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response resetPassword(@PathParam("id") String id, Map<String, Object> body) {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        String password = strOf(body.get("password"));
        if (password == null || password.length() < 8) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "PASSWORD_TOO_SHORT", "message", "Password must be at least 8 characters"))).build();
        }
        db.updateAgent(id, Map.of("passwordHash", BcryptUtil.bcryptHash(password)));
        return Response.ok(Map.of("id", id, "passwordReset", true)).build();
    }

    @DELETE
    @Path("/{id}")
    public Response deactivate(@PathParam("id") String id) {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        db.updateAgent(id, Map.of("isActive", 0));
        return Response.ok(Map.of("id", id, "isActive", false)).build();
    }

    private Response validateFields(String name, String email, String role, String password, boolean requirePassword) {
        if (name == null || name.isBlank()) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "NAME_REQUIRED", "message", "Name is required"))).build();
        }
        if (email == null || !EMAIL_RE.matcher(email).matches()) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "EMAIL_INVALID", "message", "A valid email is required"))).build();
        }
        if (role == null || !VALID_ROLES.contains(role)) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "ROLE_INVALID", "message", "Role must be one of admin, lead, agent"))).build();
        }
        if (requirePassword && (password == null || password.length() < 8)) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "PASSWORD_TOO_SHORT", "message", "Password must be at least 8 characters"))).build();
        }
        return null;
    }

    private static String strOf(Object v) {
        return v == null ? null : String.valueOf(v);
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage agents"))).build();
    }
}
