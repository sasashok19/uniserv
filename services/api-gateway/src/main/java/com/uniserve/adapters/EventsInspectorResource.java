package com.uniserve.adapters;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uniserve.events.EventStreams;
import io.quarkus.redis.datasource.RedisDataSource;
import io.quarkus.redis.datasource.stream.StreamMessage;
import io.quarkus.redis.datasource.stream.StreamRange;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.List;
import java.util.Map;

/**
 * Dev inspection endpoint (Feature 02b test stub):
 * {@code GET /api/v1/internal/events/latest?stream=channel.message.received}.
 *
 * <p>Returns the most recent event on the tenant-scoped stream, with the
 * channel-specific payload flattened to the top level so callers see
 * {@code channel}, {@code channelIdentity}, {@code rawText}, etc.
 *
 * <p>PHASE_1: unauthenticated (see 11_MULTI_TENANCY).
 */
@Path("/api/v1/internal/events/latest")
public class EventsInspectorResource {

    @Inject
    RedisDataSource redis;

    @Inject
    ObjectMapper mapper;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String tenantId;

    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Response latest(@QueryParam("stream") String stream) {
        if (stream == null || stream.isBlank()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(Map.of("error", "query parameter 'stream' is required"))
                    .build();
        }

        String key = EventStreams.key(tenantId, stream);
        var commands = redis.stream(String.class, String.class, String.class);

        List<StreamMessage<String, String, String>> messages =
                commands.xrevrange(key, StreamRange.of("-", "+"), 1);
        if (messages.isEmpty()) {
            // Fallback (robust to xrevrange range semantics): read ascending, take the last.
            List<StreamMessage<String, String, String>> ascending =
                    commands.xrange(key, StreamRange.of("-", "+"), 1024);
            if (!ascending.isEmpty()) {
                messages = List.of(ascending.get(ascending.size() - 1));
            }
        }

        if (messages.isEmpty()) {
            return Response.status(Response.Status.NOT_FOUND)
                    .entity(Map.of("error", "no events on stream " + key))
                    .build();
        }

        Map<String, String> fields = messages.get(0).payload();
        Map<String, Object> event = flatten(fields);
        event.put("messageId", messages.get(0).id());
        return Response.ok(event).build();
    }

    /** Reconstruct the event: envelope fields + the parsed channel payload. */
    private Map<String, Object> flatten(Map<String, String> fields) {
        Map<String, Object> event = new java.util.LinkedHashMap<>();
        String payload = fields.get("payload");
        if (payload != null && !payload.isBlank()) {
            try {
                event.putAll(mapper.readValue(payload, new TypeReference<Map<String, Object>>() {
                }));
            } catch (Exception ignored) {
                event.put("payload", payload);
            }
        }
        // Envelope fields (do not overwrite payload keys of the same name).
        for (String k : List.of("id", "tenantId", "type", "timestamp", "traceId")) {
            event.putIfAbsent(k, fields.get(k));
        }
        return event;
    }
}
