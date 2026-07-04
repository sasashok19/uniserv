package com.uniserve.events;

import java.util.List;

/**
 * Catalogue of the logical (tenant-agnostic) event-bus stream names owned by
 * Feature 01, plus the helper that builds the tenant-scoped Valkey key.
 *
 * <p>On the wire every stream is namespaced per tenant as {@code "{tenant}:{stream}"}
 * (e.g. {@code "acme:ticket.created"}); the constants below are the bare logical names.
 */
public final class EventStreams {

    private EventStreams() {
    }

    public static final String CHANNEL_MESSAGE_RECEIVED = "channel.message.received";
    public static final String IDENTITY_RESOLVED = "identity.resolved";
    public static final String COMPLAINT_READY = "complaint.ready";
    public static final String TICKET_CREATED = "ticket.created";
    public static final String TICKET_UPDATED = "ticket.updated";
    public static final String AI_REPLY_SEND = "ai.reply.send";
    public static final String DLQ = "dlq";

    /** All logical stream names managed by the event bus. */
    public static final List<String> ALL = List.of(
            CHANNEL_MESSAGE_RECEIVED,
            IDENTITY_RESOLVED,
            COMPLAINT_READY,
            TICKET_CREATED,
            TICKET_UPDATED,
            AI_REPLY_SEND,
            DLQ
    );

    /** Build the tenant-scoped stream key: {@code "{tenantId}:{stream}"}. */
    public static String key(String tenantId, String stream) {
        return tenantId + ":" + stream;
    }
}
