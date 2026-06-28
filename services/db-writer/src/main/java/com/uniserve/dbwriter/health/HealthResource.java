package com.uniserve.dbwriter.health;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.util.Map;

/**
 * Convenience health endpoint for the db-writer service.
 * Phase 1 scaffold: confirms the service is reachable. The read/write REST
 * API and SQLite persistence are added in 04_DB_WRITER_SERVICE.
 */
@Path("/api/v1/health")
public class HealthResource {

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, String> health() {
        return Map.of(
                "service", "db-writer",
                "status", "UP"
        );
    }
}
