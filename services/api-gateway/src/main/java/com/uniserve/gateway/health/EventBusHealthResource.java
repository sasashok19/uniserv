package com.uniserve.gateway.health;

import com.uniserve.events.EventStreams;
import io.quarkus.redis.datasource.RedisDataSource;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.jboss.logging.Logger;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Event-bus health endpoint (Feature 01 test stub):
 * {@code GET /api/v1/health/eventbus}.
 *
 * <p>Verifies Valkey connectivity with a lightweight command and reports the
 * catalogue of streams the bus manages. Returns 200 when connected, 503 otherwise.
 *
 * <p>PHASE_1: unauthenticated — the {@code Authorization: Bearer} guard in the
 * documented stub is enforced once JWT verification is wired in 11_MULTI_TENANCY.
 */
@Path("/api/v1/health/eventbus")
public class EventBusHealthResource {

    private static final Logger LOG = Logger.getLogger(EventBusHealthResource.class);

    @Inject
    RedisDataSource redis;

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Response health() {
        boolean connected = pingValkey();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", connected ? "healthy" : "unhealthy");
        body.put("valkey", connected ? "connected" : "disconnected");
        body.put("streams", EventStreams.ALL);

        return Response.status(connected ? Response.Status.OK : Response.Status.SERVICE_UNAVAILABLE)
                .entity(body)
                .build();
    }

    private boolean pingValkey() {
        try {
            // A cheap round-trip that fails fast if the connection is down.
            redis.key(String.class).exists("__eventbus_health__");
            return true;
        } catch (Exception e) {
            LOG.warnf("Event-bus health check failed to reach Valkey: %s", e.getMessage());
            return false;
        }
    }
}
