package com.uniserve.gateway.health;

import io.quarkus.redis.datasource.RedisDataSource;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Aggregate health for the whole stack (Feature 16): {@code GET /api/v1/health}.
 * Reports api-gateway (self), Valkey, db-writer and ai-core.
 */
@Path("/api/v1/health")
public class HealthResource {

    @Inject
    RedisDataSource redis;

    @ConfigProperty(name = "gateway.db-writer.url", defaultValue = "http://localhost:8090")
    String dbWriterUrl;

    @ConfigProperty(name = "gateway.ai-core.url", defaultValue = "http://localhost:8001")
    String aiCoreUrl;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3)).build();

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> health() {
        Map<String, Object> services = new LinkedHashMap<>();
        services.put("apiGateway", "healthy");
        services.put("valkey", pingValkey() ? "healthy" : "unhealthy");
        services.put("dbWriter", probe(dbWriterUrl + "/q/health/ready") ? "healthy" : "unhealthy");
        services.put("aiCore", probe(aiCoreUrl + "/q/health/ready") ? "healthy" : "unhealthy");

        boolean allHealthy = services.values().stream().allMatch("healthy"::equals);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", allHealthy ? "healthy" : "degraded");
        body.put("services", services);
        return body;
    }

    private boolean pingValkey() {
        try {
            redis.key(String.class).exists("__health__");
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private boolean probe(String url) {
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(3)).GET().build();
            HttpResponse<Void> resp = http.send(req, HttpResponse.BodyHandlers.discarding());
            return resp.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }
}
