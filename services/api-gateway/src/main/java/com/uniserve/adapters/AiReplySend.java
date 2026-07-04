package com.uniserve.adapters;

/**
 * Outbound reply event (Feature 02f). Produced by ai-core, consumed by the
 * originating adapter in api-gateway to deliver a message back to the customer.
 */
public record AiReplySend(
        String channel,
        String threadId,
        String channelIdentityValue,
        String messageText,
        boolean isIdentityRequest,
        boolean isAnonymousAck,
        String ticketRefId        // null until a ticket is created
) {
}
