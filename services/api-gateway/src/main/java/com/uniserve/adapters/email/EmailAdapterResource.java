package com.uniserve.adapters.email;

// Email ingestion is webhook-only.
// Make.com watches Gmail/Outlook and POSTs to POST /api/v1/webhooks/email.
// IMAP polling was removed — do not re-add it.
// PHASE_2: WhatsApp webhook follows the same pattern in 02b_ADAPTER_WHATSAPP.md

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/**
 * Dev/ops endpoint for the email adapter (Feature 02a test stubs):
 * {@code POST /api/v1/internal/adapters/email/test-send} — send a test outbound email.
 *
 * <p>PHASE_1: unauthenticated (see 11_MULTI_TENANCY).
 */
@Path("/api/v1/internal/adapters/email")
public class EmailAdapterResource {

    @Inject
    EmailAdapter emailAdapter;

    public record TestSendRequest(String to, String subject, String body) {
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
                null);
        return Response.ok(Map.of("sent", sent)).build();
    }
}
