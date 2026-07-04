package com.uniserve.adapters;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uniserve.events.BaseEvent;
import com.uniserve.events.EventBusPublisher;
import com.uniserve.events.EventStreams;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.Map;

/**
 * Publishes a canonical {@link ChannelMessageReceived} onto the event bus
 * (Feature 02). The channel-specific fields ride in the {@link BaseEvent}
 * payload so consumers get the full message while keeping the shared envelope.
 */
@ApplicationScoped
public class ChannelMessagePublisher {

    private final EventBusPublisher bus;
    private final ObjectMapper mapper;

    @Inject
    public ChannelMessagePublisher(EventBusPublisher bus, ObjectMapper mapper) {
        this.bus = bus;
        this.mapper = mapper;
    }

    /** Publish to {@code {tenant}:channel.message.received}; returns the message ID. */
    public String publish(ChannelMessageReceived message) {
        Map<String, Object> payload = mapper.convertValue(message, new TypeReference<>() {
        });
        BaseEvent event = new BaseEvent(
                message.id(),
                message.tenantId(),
                message.type(),
                message.timestamp(),
                message.traceId(),
                payload);
        return bus.publish(EventStreams.CHANNEL_MESSAGE_RECEIVED, event);
    }
}
