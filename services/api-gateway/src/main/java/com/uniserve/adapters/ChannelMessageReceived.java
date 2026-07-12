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

        String traceId,

        // Email subject line (Feature 09/15) — carries a ticket number
        // (e.g. "Re: ... [Ticket TKT-00042]") when the citizen replied to a
        // prior thread, letting the dedup pipeline match it precisely
        // instead of guessing by identity+category. Null for channels
        // without a subject concept (WhatsApp) or older callers.
        String subject
) {
    public static final String TYPE = "channel.message.received";

    /** Compatibility constructor for callers that predate the {@code subject} field. */
    public ChannelMessageReceived(
            String id, String tenantId, String type, String timestamp,
            String channel, ChannelIdentity channelIdentity,
            String rawText, List<String> rawMediaUrls, String languageHint,
            String threadId, String inReplyTo,
            String sentAt, String receivedAt,
            String traceId) {
        this(id, tenantId, type, timestamp, channel, channelIdentity, rawText, rawMediaUrls,
                languageHint, threadId, inReplyTo, sentAt, receivedAt, traceId, null);
    }
}
