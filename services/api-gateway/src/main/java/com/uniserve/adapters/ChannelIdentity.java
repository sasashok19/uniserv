package com.uniserve.adapters;

/**
 * Who a channel message came from (Feature 02f).
 *
 * @param type     "phone" | "email" | "handle" | "session" | "unknown"
 * @param value    e.g. "+919876543210" or "user@example.com" (may be null)
 * @param verified true when the channel natively confirms the identity
 *                 (WhatsApp phone = true; email = false)
 */
public record ChannelIdentity(
        String type,
        String value,
        boolean verified
) {
}
