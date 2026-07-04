package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.JsonNode;
import com.uniserve.adapters.ChannelIdentity;
import com.uniserve.adapters.ChannelMessageReceived;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Parses a Meta WhatsApp Business webhook payload into canonical
 * {@link ChannelMessageReceived} events (Feature 02b).
 *
 * <p>Pure logic (JsonNode in, records out) so it can be unit-tested without a
 * running server. Identity is always {@code phone / verified=true} — the phone
 * number is provided natively by Meta, so the identity gate is skipped downstream.
 */
public final class WhatsAppParser {

    private WhatsAppParser() {
    }

    public static List<ChannelMessageReceived> parse(JsonNode root, String tenantId) {
        List<ChannelMessageReceived> events = new ArrayList<>();
        if (root == null) {
            return events;
        }
        for (JsonNode entry : root.path("entry")) {
            for (JsonNode change : entry.path("changes")) {
                JsonNode value = change.path("value");
                for (JsonNode message : value.path("messages")) {
                    events.add(toEvent(message, tenantId));
                }
            }
        }
        return events;
    }

    private static ChannelMessageReceived toEvent(JsonNode message, String tenantId) {
        String from = message.path("from").asText(null);
        String phone = toE164(from);
        String type = message.path("type").asText("");

        String rawText = extractText(message, type);
        List<String> media = extractMedia(message, type);
        String inReplyTo = message.path("context").path("id").asText(null);

        String nowIso = Instant.now().toString();
        String sentAt = toIso(message.path("timestamp").asText(null), nowIso);

        return new ChannelMessageReceived(
                UUID.randomUUID().toString(),
                tenantId,
                ChannelMessageReceived.TYPE,
                nowIso,
                "whatsapp",
                new ChannelIdentity("phone", phone, true),
                rawText,
                media,
                null,               // languageHint
                null,               // threadId (WhatsApp threads by phone; not tracked in Phase 1)
                inReplyTo,
                sentAt,
                nowIso,
                UUID.randomUUID().toString());
    }

    private static String extractText(JsonNode message, String type) {
        return switch (type) {
            case "text" -> message.path("text").path("body").asText(null);
            case "interactive" -> {
                JsonNode interactive = message.path("interactive");
                JsonNode button = interactive.path("button_reply");
                if (!button.isMissingNode()) {
                    yield button.path("title").asText(null);
                }
                yield interactive.path("list_reply").path("title").asText(null);
            }
            default -> null;
        };
    }

    private static List<String> extractMedia(JsonNode message, String type) {
        List<String> media = new ArrayList<>();
        if (type.equals("image") || type.equals("document") || type.equals("audio") || type.equals("video")) {
            String id = message.path(type).path("id").asText(null);
            if (id != null) {
                // Phase 1: store the Meta media id; Graph-API URL resolution is added later.
                media.add(id);
            }
        }
        return media;
    }

    /** Normalise a bare digit string to E.164 (prefix "+"); null-safe. */
    static String toE164(String number) {
        if (number == null || number.isBlank()) {
            return null;
        }
        return number.startsWith("+") ? number : "+" + number;
    }

    private static String toIso(String epochSeconds, String fallback) {
        if (epochSeconds == null || epochSeconds.isBlank()) {
            return fallback;
        }
        try {
            return Instant.ofEpochSecond(Long.parseLong(epochSeconds)).toString();
        } catch (NumberFormatException e) {
            return fallback;
        }
    }
}
