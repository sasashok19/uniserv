package com.uniserve.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/** Tenant configuration (Feature 11) — Admin only. */
@Path("/api/v1/tenant/config")
@Produces(MediaType.APPLICATION_JSON)
public class TenantConfigResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @Inject
    ObjectMapper mapper;

    @GET
    public Response get() {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Map<String, Object> tenant = db.getTenant(user.tenantId());
        return Response.ok(parseConfig(tenant)).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> config) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        try {
            String json = mapper.writeValueAsString(config);
            Map<String, Object> tenant = db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(parseConfig(tenant)).build();
        } catch (Exception e) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "INVALID_CONFIG", "message", e.getMessage()))).build();
        }
    }

    private Object parseConfig(Map<String, Object> tenant) {
        Object raw = tenant.get("config_json");
        if (raw == null) {
            return Map.of();
        }
        try {
            return mapper.readValue(String.valueOf(raw), new TypeReference<Map<String, Object>>() {
            });
        } catch (Exception e) {
            return Map.of();
        }
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage tenant configuration"))).build();
    }
}
