package com.uniserve.auth;

import io.quarkus.elytron.security.common.BcryptUtil;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;
import java.util.Optional;

/**
 * Admin system operations (UI_REVAMP_v2 Feature D) — currently the tenant DB
 * reset. Layered safeguards, in order:
 * <ol>
 *   <li>Path is in {@link AuthFilter#isProtected} ({@code api/v1/admin}), so a
 *       valid JWT is required.</li>
 *   <li>RBAC: {@code admin.system.reset} — admin role only.</li>
 *   <li>The admin must re-enter their CURRENT password, verified against the
 *       stored bcrypt hash (same {@link BcryptUtil} check as login).</li>
 *   <li>The literal confirmation string {@code RESET} must be supplied
 *       (re-checked in db-writer too).</li>
 *   <li>db-writer rate-limits to one reset per tenant per 60s.</li>
 * </ol>
 * The calling admin's account and the tenants row survive the reset.
 */
@Path("/api/v1/admin")
@Produces(MediaType.APPLICATION_JSON)
public class SystemAdminResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @POST
    @Path("/reset")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response reset(Map<String, Object> body) {
        if (!user.can("admin.system.reset")) {
            return error(403, "INSUFFICIENT_ROLE", "Only admins can reset the database");
        }
        String password = str(body, "password");
        String confirmation = str(body, "confirmation");
        if (!"RESET".equals(confirmation)) {
            return error(400, "CONFIRMATION_REQUIRED", "Type RESET to confirm");
        }
        if (password == null || password.isBlank()) {
            return error(401, "INVALID_PASSWORD", "Password is required");
        }
        Optional<Map<String, Object>> agentOpt = db.findAgentByEmail(user.email());
        String hash = agentOpt.map(a -> str(a, "password_hash")).orElse(null);
        if (hash == null || !BcryptUtil.matches(password, hash)) {
            return error(401, "INVALID_PASSWORD", "Incorrect password");
        }

        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/admin/reset", Map.of(
                "tenantId", user.tenantId(),
                "adminAgentId", user.agentId(),
                "confirmation", "RESET"));
        if (result.status() == 429) {
            return Response.status(429).entity(Map.of(
                    "error", Map.of("code", "RATE_LIMITED", "message", "Please wait before trying again"),
                    "retryAfterSeconds", 60)).build();
        }
        if (result.status() >= 400) {
            return Response.status(result.status()).entity(result.body()).build();
        }
        return Response.ok(Map.of("message", "Reset complete", "adminEmail", user.email())).build();
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private Response error(int status, String code, String message) {
        return Response.status(status).entity(Map.of(
                "error", Map.of("code", code, "message", message))).build();
    }
}
