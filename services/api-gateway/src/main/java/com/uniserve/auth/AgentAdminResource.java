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

/** Agent management (Feature 11) — Admin only. Proxies to db-writer. */
@Path("/api/v1/agents")
@Produces(MediaType.APPLICATION_JSON)
public class AgentAdminResource {

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
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("tenantId", user.tenantId());
        payload.put("name", body.get("name"));
        payload.put("email", body.get("email"));
        payload.put("role", body.get("role"));
        payload.put("passwordHash", BcryptUtil.bcryptHash(String.valueOf(body.get("password"))));

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

    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(@PathParam("id") String id, Map<String, Object> body) {
        if (!user.can("admin.agents.manage")) {
            return forbidden();
        }
        Map<String, Object> updated = db.updateAgent(id, body);
        updated.remove("password_hash");
        return Response.ok(updated).build();
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

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage agents"))).build();
    }
}
