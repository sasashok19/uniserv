package com.uniserve.events;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.quarkus.redis.datasource.RedisDataSource;
import io.quarkus.redis.datasource.stream.StreamCommands;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Plain unit tests for {@link EventBusPublisher} — no Quarkus boot and no live
 * Valkey required (the Redis stream commands are mocked). Validates the first
 * unit-test requirement in 01_EVENT_BUS: "Publisher writes to correct stream
 * with correct shape".
 */
class EventBusPublisherTest {

    @SuppressWarnings("unchecked")
    private final StreamCommands<String, String, String> streamCommands = mock(StreamCommands.class);
    private EventBusPublisher publisher;

    @BeforeEach
    void setUp() {
        RedisDataSource redis = mock(RedisDataSource.class);
        when(redis.stream(String.class, String.class, String.class)).thenReturn(streamCommands);
        publisher = new EventBusPublisher(redis, new ObjectMapper());
    }

    @Test
    void publishesToTenantScopedStreamWithEnvelopeShape() {
        when(streamCommands.xadd(eq("acme:ticket.created"), anyMap())).thenReturn("1526919030474-0");

        BaseEvent event = new BaseEvent(
                "evt-1", "acme", "ticket.created", "2026-07-04T10:00:00Z", "trace-1",
                Map.of("ticketId", "T-100", "priority", "high"));

        String messageId = publisher.publish(EventStreams.TICKET_CREATED, event);

        assertEquals("1526919030474-0", messageId);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> fieldsCaptor = ArgumentCaptor.forClass(Map.class);
        verify(streamCommands).xadd(eq("acme:ticket.created"), fieldsCaptor.capture());

        Map<String, String> fields = fieldsCaptor.getValue();
        assertEquals("evt-1", fields.get("id"));
        assertEquals("acme", fields.get("tenantId"));
        assertEquals("ticket.created", fields.get("type"));
        assertEquals("2026-07-04T10:00:00Z", fields.get("timestamp"));
        assertEquals("trace-1", fields.get("traceId"));
        // payload is serialized as a JSON string
        assertTrue(fields.get("payload").contains("\"ticketId\":\"T-100\""), fields.get("payload"));
        assertTrue(fields.get("payload").contains("\"priority\":\"high\""), fields.get("payload"));
    }

    @Test
    void routesFailedEventToTenantDlqWithReason() {
        when(streamCommands.xadd(eq("acme:dlq"), anyMap())).thenReturn("1526919031000-0");

        BaseEvent event = BaseEvent.of("acme", "ticket.created", "trace-9", Map.of("ticketId", "T-200"));

        String messageId = publisher.publishToDlq(EventStreams.TICKET_CREATED, event, "handler timed out");

        assertEquals("1526919031000-0", messageId);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> fieldsCaptor = ArgumentCaptor.forClass(Map.class);
        verify(streamCommands).xadd(eq("acme:dlq"), fieldsCaptor.capture());

        Map<String, String> fields = fieldsCaptor.getValue();
        assertEquals("ticket.created", fields.get("originalStream"));
        assertEquals("handler timed out", fields.get("error"));
        assertTrue(fields.containsKey("failedAt"));
    }
}
