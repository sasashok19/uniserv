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
     * interactive message: entries of {@code {"id": ..., "title": ...}}, with an
     * optional {@code "description"} (Feature 29). Both optional — omitting them
     * sends plain text exactly as before, so every existing caller is unaffected.
     *
     * <p>The field is still called {@code buttons} for wire compatibility, but
     * the adapter decides the rendering: more than three entries, or any entry
     * with a description, goes out as a <b>list</b> message instead, since Meta
     * caps reply-buttons at three. {@code listLabel} names the strip that opens
     * that list and is ignored when the entries render as buttons.
     */
    public record SendRequest(String to, String body, String contextMessageId,
                              java.util.List<Map<String, String>> buttons, String footer,
                              String listLabel) {
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
                request.footer(),
                request.listLabel());
        // Feature 24: the wamid goes back to the caller (ai-core) so it can
        // stamp it onto the ticket_message row it already persisted — that is
        // what makes the citizen's reply to THIS message routable.
        Map<String, Object> body = new java.util.LinkedHashMap<>();
        body.put("sent", result.sent());
        body.put("channelMessageId", result.channelMessageId());
        return Response.ok(body).build();
    }
}
