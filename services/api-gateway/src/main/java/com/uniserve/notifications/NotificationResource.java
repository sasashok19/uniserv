package com.uniserve.notifications;

import io.quarkus.mailer.Mail;
import io.quarkus.mailer.Mailer;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.jboss.logging.Logger;

import java.util.Map;

/**
 * Notifications (Feature 14). PHASE_1: outbound email via the Quarkus mailer
 * (mock mode in dev — messages are logged, not delivered). SMS/webhook are Phase 2.
 *
 * <p>Test stub: {@code POST /api/v1/internal/notifications/test}.
 */
@Path("/api/v1/internal/notifications")
@Produces(MediaType.APPLICATION_JSON)
public class NotificationResource {

    private static final Logger LOG = Logger.getLogger(NotificationResource.class);

    @Inject
    Mailer mailer;

    @POST
    @Path("/test")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response test(Map<String, Object> body) {
        String to = str(body, "to");
        if (to == null || to.isBlank()) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "TO_REQUIRED", "message", "'to' is required"))).build();
        }
        NotificationTemplates.Message msg = NotificationTemplates.build(
                str(body, "type"), str(body, "ticketNumber"), str(body, "category"));

        mailer.send(Mail.withHtml(to, msg.subject(), msg.body()));
        LOG.infof("Notification sent type=%s to=%s", str(body, "type"), to);
        return Response.ok(Map.of("sent", true, "channel", "email")).build();
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
