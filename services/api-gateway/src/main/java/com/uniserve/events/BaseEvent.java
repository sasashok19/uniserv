package com.uniserve.events;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Envelope for every message on the Valkey-Streams event bus (Feature 01).
 *
 * <p>The shape is shared across services (Java + Python): {@code id}, {@code tenantId},
 * {@code type}, {@code timestamp} (ISO-8601), {@code traceId} and a free-form
 * {@code payload}. Message schemas for specific event types are owned by Feature 02f,
 * not here — this is purely the transport envelope.
 */
public record BaseEvent(
        String id,
        String tenantId,
        String type,
        String timestamp,
        String traceId,
        Map<String, Object> payload
) {

    /**
     * Build an event, generating {@code id}, {@code timestamp} and (when absent)
     * {@code traceId}. Callers supply the tenant, logical type and payload.
     */
    public static BaseEvent of(String tenantId, String type, String traceId, Map<String, Object> payload) {
        return new BaseEvent(
                UUID.randomUUID().toString(),
                tenantId,
                type,
                Instant.now().toString(),
                (traceId == null || traceId.isBlank()) ? UUID.randomUUID().toString() : traceId,
                payload == null ? Map.of() : payload
        );
    }
}
