package com.uniserve.events;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.quarkus.redis.datasource.RedisDataSource;
import io.quarkus.redis.datasource.stream.StreamCommands;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Publishes {@link BaseEvent}s to Valkey Streams (Feature 01).
 *
 * <p>Each event is written with {@code XADD} to the tenant-scoped stream key
 * {@code "{tenant}:{stream}"}. The envelope fields are stored as flat stream
 * fields; the free-form {@code payload} is stored as a JSON string so consumers
 * in any language can reconstruct it.
 */
@ApplicationScoped
public class EventBusPublisher {

    private final StreamCommands<String, String, String> streams;
    private final ObjectMapper mapper;

    @Inject
    public EventBusPublisher(RedisDataSource redis, ObjectMapper mapper) {
        this.streams = redis.stream(String.class, String.class, String.class);
        this.mapper = mapper;
    }

    /**
     * Publish an event to the given logical stream for its tenant.
     *
     * @param stream logical stream name (see {@link EventStreams})
     * @param event  the event envelope; its {@code tenantId} scopes the stream key
     * @return the Valkey-generated message ID
     */
    public String publish(String stream, BaseEvent event) {
        String key = EventStreams.key(event.tenantId(), stream);
        return streams.xadd(key, toFields(event));
    }

    /**
     * Route a failed event to the tenant's dead-letter queue, preserving the
     * originating stream and the failure reason for manual review.
     *
     * @return the Valkey-generated message ID of the DLQ entry
     */
    public String publishToDlq(String originalStream, BaseEvent event, String error) {
        String key = EventStreams.key(event.tenantId(), EventStreams.DLQ);
        Map<String, String> fields = toFields(event);
        fields.put("originalStream", originalStream);
        fields.put("error", error == null ? "" : error);
        fields.put("failedAt", Instant.now().toString());
        return streams.xadd(key, fields);
    }

    private Map<String, String> toFields(BaseEvent event) {
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("id", event.id());
        fields.put("tenantId", event.tenantId());
        fields.put("type", event.type());
        fields.put("timestamp", event.timestamp());
        fields.put("traceId", event.traceId() == null ? "" : event.traceId());
        try {
            fields.put("payload", mapper.writeValueAsString(event.payload() == null ? Map.of() : event.payload()));
        } catch (JsonProcessingException e) {
            throw new EventBusException("Failed to serialize payload for event " + event.id(), e);
        }
        return fields;
    }
}
