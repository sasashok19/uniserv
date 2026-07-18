package com.uniserve.adapters.email;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/**
 * Dev/ops endpoints for the email adapter (Feature 02a test stubs):
 * <ul>
 *   <li>{@code POST /api/v1/internal/adapters/email/poll} — trigger a manual IMAP poll.</li>
 *   <li>{@code POST /api/v1/internal/adapters/email/test-send} — send a test outbound email.</li>
 * </ul>
 *
 * <p>PHASE_1: unauthenticated (see 11_MULTI_TENANCY).
 */
@Path("/api/v1/internal/adapters/email")
public class EmailAdapterResource {

    @Inject
    EmailAdapter emailAdapter;

    /** {@code inReplyToMessageId} (Feature 15) — the ticket's origin inbound Message-ID, when
     * known, so this email threads into the same chain instead of arriving as a fresh message. */
    public record TestSendRequest(String to, String subject, String body, String inReplyToMessageId) {
    }

    @POST
    @Path("/poll")
    @Produces(MediaType.APPLICATION_JSON)
    public Response poll() {
        EmailAdapter.PollResult result = emailAdapter.pollOnce();
        return Response.ok(Map.of(
                "messagesProcessed", result.messagesProcessed(),
                "errors", result.errors())).build();
    }

    @POST
    @Path("/test-send")
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response testSend(TestSendRequest request) {
        if (request == null || request.to() == null || request.to().isBlank()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(Map.of("sent", false, "error", "'to' is required"))
                    .build();
        }
        boolean sent = emailAdapter.sendReply(
                request.to(),
                request.subject() == null ? "(no subject)" : request.subject(),
                request.body() == null ? "" : request.body(),
                request.inReplyToMessageId());
        return Response.ok(Map.of("sent", sent)).build();
    }
}
