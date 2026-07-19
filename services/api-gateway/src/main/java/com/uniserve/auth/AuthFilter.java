package com.uniserve.auth;

import com.auth0.jwt.exceptions.TokenExpiredException;
import com.auth0.jwt.interfaces.DecodedJWT;
import jakarta.inject.Inject;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;

import java.util.Map;

/**
 * JWT authentication for the RBAC-protected api-gateway endpoints (Feature 11/15):
 * {@code /api/v1/agents}, {@code /api/v1/tenant}, {@code /api/v1/tickets},
 * {@code /api/v1/analytics}.
 *
 * <p>Verifies the {@code Authorization: Bearer} token and populates
 * {@link CurrentUser}. Other paths (health, webhooks, adapter internals) are left
 * open — they are handled by their own Phase-1 rules.
 *
 * <p><b>Adding a new RBAC-protected resource?</b> Its path prefix must be added
 * to {@link #isProtected(String)} below, or {@link CurrentUser} is silently left
 * unpopulated and every {@code user.tenantId()}/{@code user.role()} call on that
 * resource NPEs or falls through RBAC checks as if unauthenticated.
 */
@Provider
public class AuthFilter implements ContainerRequestFilter {

    // MIGRATION NOTE: If @RolesAllowed annotations are needed in future,
    // migrate to quarkus-security-jwt with scoped path matching to avoid
    // smallrye-jwt Bearer token interception conflict.

    @Inject
    JwtService jwt;

    @Inject
    CurrentUser currentUser;

    @Override
    public void filter(ContainerRequestContext ctx) {
        String path = ctx.getUriInfo().getPath();
        if (!isProtected(path)) {
            return;
        }

        String auth = ctx.getHeaderString("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) {
            abort(ctx, 401, "UNAUTHORIZED", "Authentication required");
            return;
        }

        String token = auth.substring("Bearer ".length()).trim();
        try {
            DecodedJWT decoded = jwt.verify(token);
            currentUser.set(
                    decoded.getSubject(),
                    claim(decoded, "tenant_id"),
                    claim(decoded, "role"),
                    claim(decoded, "name"),
                    claim(decoded, "email"));
        } catch (TokenExpiredException e) {
            abort(ctx, 401, "TOKEN_EXPIRED", "Access token expired");
        } catch (Exception e) {
            abort(ctx, 401, "INVALID_TOKEN", "Invalid access token");
        }
    }

    private boolean isProtected(String path) {
        // NOTE: substring matching — "/api/v1/public/announcements" (login-page
        // ticker, PublicAnnouncementsResource) deliberately does NOT match the
        // "api/v1/announcements" prefix below because of the "public/" segment.
        return path.contains("api/v1/agents")
                || path.contains("api/v1/tenant")
                || path.contains("api/v1/tickets")
                || path.contains("api/v1/analytics")
                || path.contains("api/v1/announcements")
                || path.contains("api/v1/admin");
    }

    private String claim(DecodedJWT jwt, String name) {
        return jwt.getClaim(name).asString();
    }

    private void abort(ContainerRequestContext ctx, int status, String code, String message) {
        ctx.abortWith(Response.status(status)
                .entity(Map.of("error", Map.of("code", code, "message", message)))
                .build());
    }
}
