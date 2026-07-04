package com.uniserve.adapters;

import java.util.List;

/**
 * Canonical inbound event every channel adapter emits (Feature 02f).
 *
 * <p>This is the single shape the AI pipeline consumes, regardless of whether the
 * message originated from email, WhatsApp, or (Phase 2) Twitter/IVR/WebChat.
 */
public record ChannelMessageReceived(
        String id,
        String tenantId,
        String type,           // always "channel.message.received"
        String timestamp,

        // Channel identity
        String channel,        // "email" | "whatsapp"  (P2: twitter | ivr | webchat)
        ChannelIdentity channelIdentity,

        // Content
        String rawText,
        List<String> rawMediaUrls,
        String languageHint,   // ISO 639-1 or null

        // Threading
        String threadId,
        String inReplyTo,      // message ID of parent, or null

        // Timestamps
        String sentAt,
        String receivedAt,

        String traceId
) {
    public static final String TYPE = "channel.message.received";
}
