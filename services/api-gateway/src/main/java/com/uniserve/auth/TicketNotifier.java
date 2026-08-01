package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import com.uniserve.adapters.whatsapp.WhatsAppAdapter;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

import java.util.Map;

/**
 * Structured citizen-facing notification sent when a ticket moves to resolved
 * or closed (Feature 06 x 14) — shared by the manual transition endpoint
 * ({@link TicketsResource}) and the automatic 14-day unconfirmed-ticket
 * closer ({@link TicketAutoCloseScheduler}). Delivered over email or WhatsApp
 * depending on the ticket's origin channel.
 */
@ApplicationScoped
public class TicketNotifier {

    private static final Logger LOG = Logger.getLogger(TicketNotifier.class);

    @Inject
    DbWriterClient db;

    @Inject
    EmailAdapter emailAdapter;

    @Inject
    WhatsAppAdapter whatsAppAdapter;

    /** Best-effort: a failed send never rolls back the caller's transition/close. */
    public void sendStatusUpdate(Map<String, Object> ticket, String toStatus, String noteContent) {
        String channel = str(ticket, "channel_origin");
        String identityId = str(ticket, "identity_id");
        String ticketNumber = str(ticket, "ticket_number");
        if (identityId == null || !("email".equals(channel) || "whatsapp".equals(channel))) {
            return;
        }
        DbWriterClient.ApiResult identity = db.call("GET", "/api/v1/db/identities/" + identityId, null);
        if (identity.status() >= 400) {
            return;
        }

        StringBuilder body = new StringBuilder();
        body.append("Your complaint has been updated.\n\n");
        body.append("Ticket ID: ").append(ticketNumber).append('\n');
        body.append("Status: ").append(toStatus).append('\n');
        if (noteContent != null && !noteContent.isBlank()) {
            body.append('\n').append("Note from our team:\n").append(noteContent).append('\n');
        }

        try {
            if ("email".equals(channel)) {
                String toAddress = str(identity.body(), "email");
                if (toAddress == null || toAddress.isBlank()) {
                    return;
                }
                String subject = "Your complaint " + ticketNumber + " is now " + toStatus;
                body.append("\nIf you have further questions, just reply to this email.");
                emailAdapter.sendReply(toAddress, subject, body.toString(), str(ticket, "origin_message_id"));
            } else {
                String toPhone = str(identity.body(), "phone");
                if (toPhone == null || toPhone.isBlank()) {
                    return;
                }
                body.append("\nIf you have further questions, just reply to this message.");
                whatsAppAdapter.sendReply(toPhone, body.toString(), str(ticket, "origin_message_id"));
            }
        } catch (Exception e) {
            LOG.errorf(e, "Failed to send status-update notification for ticket %s", ticket.get("id"));
        }
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
