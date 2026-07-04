package com.uniserve.dbwriter.security;

import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.Map;
import java.util.Optional;

/**
 * Pod-to-pod authentication for the db-writer data API (Feature 04): requires a
 * matching {@code X-Internal-Key} header on {@code /api/v1/db/*} requests.
 *
 * <p>PHASE_1: enforced only when {@code DB_WRITER_INTERNAL_API_KEY} is configured.
 * In dev (no key set) the filter is a no-op so local stubs work without a secret.
 */
@Provider
public class InternalKeyFilter implements ContainerRequestFilter {

    @ConfigProperty(name = "db-writer.internal-api-key")
    Optional<String> configuredKey;

    @Override
    public void filter(ContainerRequestContext ctx) {
        if (configuredKey.isEmpty() || configuredKey.get().isBlank()) {
            return; // dev / unconfigured: no pod-to-pod auth
        }
        String path = ctx.getUriInfo().getPath();
        if (path == null || !path.contains("api/v1/db/")) {
            return; // only guard the data API
        }
        String provided = ctx.getHeaderString("X-Internal-Key");
        if (!configuredKey.get().equals(provided)) {
            ctx.abortWith(Response.status(Response.Status.UNAUTHORIZED)
                    .entity(Map.of("error", Map.of(
                            "code", "UNAUTHORIZED",
                            "message", "Valid X-Internal-Key required")))
                    .build());
        }
    }
}
