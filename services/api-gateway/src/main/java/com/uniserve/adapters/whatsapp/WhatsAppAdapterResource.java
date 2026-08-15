package com.uniserve.adapters.whatsapp;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/**
 * Outbound-send endpoint for the WhatsApp adapter (Feature 02b outbound),
 * called by ai-core's {@code app/notifications/sender.py} — the WhatsApp
 * counterpart to {@code EmailAdapterResource}'s {@code /test-send}.
 *
 * <p>PHASE_1: unauthenticated (see 11_MULTI_TENANCY).
 */
@Path("/api/v1/internal/adapters/whatsapp")
public class WhatsAppAdapterResource {

    @Inject
    WhatsAppAdapter whatsAppAdapter;

    /**
     * {@code contextMessageId} — the citizen's inbound wamid (Feature 15 parity), when
     * known, so this reply renders as a quoted reply-to instead of a fresh message.
     *
     * <p>{@code buttons} and {@code footer} (Feature 28) turn the send into an
     * interactive reply-buttons message: up to 3 entries of
     * {@code {"id": ..., "title": ...}}. Both optional — omitting them sends
     * plain text exactly as before, so every existing caller is unaffected.
     */
    public record SendRequest(String to, String body, String contextMessageId,
                              java.util.List<Map<String, String>> buttons, String footer) {
    }

    @POST
    @Path("/send")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response send(SendRequest request) {
        if (request == null || request.to() == null || request.to().isBlank()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(Map.of("sent", false, "error", "'to' is required"))
                    .build();
        }
        com.uniserve.adapters.SendResult result = whatsAppAdapter.sendReply(
                request.to(),
                request.body() == null ? "" : request.body(),
                request.contextMessageId(),
                request.buttons(),
                request.footer());
        // Feature 24: the wamid goes back to the caller (ai-core) so it can
        // stamp it onto the ticket_message row it already persisted — that is
        // what makes the citizen's reply to THIS message routable.
        Map<String, Object> body = new java.util.LinkedHashMap<>();
        body.put("sent", result.sent());
        body.put("channelMessageId", result.channelMessageId());
        return Response.ok(body).build();
    }
}
