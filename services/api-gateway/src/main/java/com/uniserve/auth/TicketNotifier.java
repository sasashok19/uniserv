package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

import java.util.Map;

/**
 * Structured citizen-facing email sent when a ticket moves to resolved or
 * closed (Feature 06 x 14) — shared by the manual transition endpoint
 * ({@link TicketsResource}) and the automatic 14-day unconfirmed-ticket
 * closer ({@link TicketAutoCloseScheduler}).
 */
@ApplicationScoped
public class TicketNotifier {

    private static final Logger LOG = Logger.getLogger(TicketNotifier.class);

    @Inject
    DbWriterClient db;

    @Inject
    EmailAdapter emailAdapter;

    /** Best-effort: a failed send never rolls back the caller's transition/close. */
    public void sendStatusUpdateEmail(Map<String, Object> ticket, String toStatus, String noteContent) {
        String channel = str(ticket, "channel_origin");
        String identityId = str(ticket, "identity_id");
        String ticketNumber = str(ticket, "ticket_number");
        if (!"email".equals(channel) || identityId == null) {
            return;
        }
        DbWriterClient.ApiResult identity = db.call("GET", "/api/v1/db/identities/" + identityId, null);
        String toAddress = identity.status() < 400 ? str(identity.body(), "email") : null;
        if (toAddress == null || toAddress.isBlank()) {
            return;
        }
        String subject = "Your complaint " + ticketNumber + " is now " + toStatus;
        StringBuilder body = new StringBuilder();
        body.append("Your complaint has been updated.\n\n");
        body.append("Ticket ID: ").append(ticketNumber).append('\n');
        body.append("Status: ").append(toStatus).append('\n');
        if (noteContent != null && !noteContent.isBlank()) {
            body.append('\n').append("Note from our team:\n").append(noteContent).append('\n');
        }
        body.append("\nIf you have further questions, just reply to this email.");
        try {
            emailAdapter.sendReply(toAddress, subject, body.toString(), null);
        } catch (Exception e) {
            LOG.errorf(e, "Failed to send status-update email for ticket %s", ticket.get("id"));
        }
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
