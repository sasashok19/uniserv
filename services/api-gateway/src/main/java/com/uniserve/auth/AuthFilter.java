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
 * JWT authentication for the RBAC-protected api-gateway endpoints (Feature 11):
 * {@code /api/v1/agents}, {@code /api/v1/tenant}, {@code /api/v1/tickets}.
 *
 * <p>Verifies the {@code Authorization: Bearer} token and populates
 * {@link CurrentUser}. Other paths (health, webhooks, adapter internals) are left
 * open — they are handled by their own Phase-1 rules.
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
        return path.contains("api/v1/agents")
                || path.contains("api/v1/tenant")
                || path.contains("api/v1/tickets");
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
