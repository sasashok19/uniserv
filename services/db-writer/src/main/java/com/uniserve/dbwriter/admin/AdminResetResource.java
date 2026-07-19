package com.uniserve.dbwriter.admin;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.HeaderParam;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import com.uniserve.dbwriter.common.ApiException;

import java.util.Map;

/**
 * Tenant reset endpoint (UI_REVAMP_v2 Feature D): {@code POST /api/v1/db/admin/reset}.
 * The confirmation may arrive as the {@code X-Reset-Confirmation} header or a
 * {@code confirmation} body field — the gateway sends the body field (its
 * db-writer client doesn't attach custom headers).
 */
@Path("/api/v1/db/admin")
@Produces(MediaType.APPLICATION_JSON)
public class AdminResetResource {

    @Inject
    AdminResetService reset;

    @POST
    @Path("/reset")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> reset(@HeaderParam("X-Reset-Confirmation") String confirmationHeader,
                                     Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        String adminAgentId = str(body, "adminAgentId");
        if (tenantId == null || tenantId.isBlank() || adminAgentId == null || adminAgentId.isBlank()) {
            throw new ApiException(400, "BAD_REQUEST", "tenantId and adminAgentId are required");
        }
        String confirmation = confirmationHeader != null ? confirmationHeader : str(body, "confirmation");
        Map<String, Object> counts = reset.reset(tenantId, adminAgentId, confirmation);
        return Map.of("message", "Reset complete", "deleted", counts);
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        return v == null ? null : String.valueOf(v);
    }
}
