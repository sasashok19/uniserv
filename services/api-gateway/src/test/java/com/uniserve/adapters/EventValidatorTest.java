package com.uniserve.adapters;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for the adapter-contract validator (Feature 02f). */
class EventValidatorTest {

    private static ChannelMessageReceived validEmailEvent() {
        return new ChannelMessageReceived(
                "id-1", "default", ChannelMessageReceived.TYPE, "2025-06-27T10:00:00Z",
                "email", new ChannelIdentity("email", "test@example.com", false),
                "My bill is wrong", List.of(), null,
                "thread-001", null, "2025-06-27T10:00:00Z", "2025-06-27T10:00:01Z", "trace-1");
    }

    @Test
    void acceptsWellFormedEmailEvent() {
        assertTrue(EventValidator.isValid(validEmailEvent()));
    }

    @Test
    void acceptsWhatsAppEventWithVerifiedIdentity() {
        ChannelMessageReceived event = new ChannelMessageReceived(
                "id-2", "default", ChannelMessageReceived.TYPE, "2025-06-27T10:00:00Z",
                "whatsapp", new ChannelIdentity("phone", "+919876543210", true),
                "My bill is double", List.of(), null,
                null, null, "2025-06-27T10:00:00Z", "2025-06-27T10:00:01Z", "trace-2");
        assertTrue(EventValidator.isValid(event));
    }

    @Test
    void rejectsMissingRawText() {
        ChannelMessageReceived event = new ChannelMessageReceived(
                "id-3", "default", ChannelMessageReceived.TYPE, "2025-06-27T10:00:00Z",
                "email", new ChannelIdentity("email", "test@example.com", false),
                null, List.of(), null, "thread", null, "2025-06-27T10:00:00Z", null, "trace-3");
        List<String> errors = EventValidator.validate(event);
        assertFalse(errors.isEmpty());
        assertTrue(errors.stream().anyMatch(e -> e.contains("rawText")));
    }

    @Test
    void rejectsMissingChannelAndSentAt() {
        ChannelMessageReceived event = new ChannelMessageReceived(
                "id-4", "default", ChannelMessageReceived.TYPE, "2025-06-27T10:00:00Z",
                null, new ChannelIdentity("email", "test@example.com", false),
                "text", List.of(), null, "thread", null, null, null, "trace-4");
        List<String> errors = EventValidator.validate(event);
        assertTrue(errors.stream().anyMatch(e -> e.contains("channel")));
        assertTrue(errors.stream().anyMatch(e -> e.contains("sentAt")));
    }

    @Test
    void rejectsUnknownChannel() {
        ChannelMessageReceived event = new ChannelMessageReceived(
                "id-5", "default", ChannelMessageReceived.TYPE, "2025-06-27T10:00:00Z",
                "carrier-pigeon", new ChannelIdentity("email", "x@example.com", false),
                "text", List.of(), null, "thread", null, "2025-06-27T10:00:00Z", null, "trace-5");
        assertFalse(EventValidator.isValid(event));
    }
}
