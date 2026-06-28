package com.uniserve.gateway.health;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.util.Map;

/**
 * Convenience health endpoint for the api-gateway service.
 * Phase 1 scaffold: confirms the service is reachable. Feature endpoints
 * (channel adapters, auth, routing) are added in later features.
 */
@Path("/api/v1/health")
public class HealthResource {

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, String> health() {
        return Map.of(
                "service", "api-gateway",
                "status", "UP"
        );
    }
}
