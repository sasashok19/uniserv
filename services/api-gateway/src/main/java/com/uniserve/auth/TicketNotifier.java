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
            com.uniserve.adapters.SendResult result;
            if ("email".equals(channel)) {
                String toAddress = str(identity.body(), "email");
                if (toAddress == null || toAddress.isBlank()) {
                    return;
                }
                String subject = "Your complaint " + ticketNumber + " is now " + toStatus;
                body.append("\nIf you have further questions, just reply to this email.");
                result = emailAdapter.sendReply(
                        toAddress, subject, body.toString(), str(ticket, "origin_message_id"));
            } else {
                String toPhone = str(identity.body(), "phone");
                if (toPhone == null || toPhone.isBlank()) {
                    return;
                }
                body.append("\nIf you have further questions, just reply to this message.");
                result = whatsAppAdapter.sendReply(
                        toPhone, body.toString(), str(ticket, "origin_message_id"));
            }
            recordOnConversation(str(ticket, "id"), channel, body.toString(),
                    result == null ? null : result.channelMessageId());
        } catch (Exception e) {
            LOG.errorf(e, "Failed to send status-update notification for ticket %s", ticket.get("id"));
        }
    }

    /**
     * Put the notification we just sent onto the ticket's conversation
     * (Feature 24).
     *
     * It was previously sent and then forgotten — invisible in the dashboard, so
     * an agent could not see what the citizen had been told, and invisible to
     * routing, which matters more than it sounds: this message explicitly invites
     * a reply ("just reply to this email"), and a citizen who takes it up on that
     * produces exactly the inbound "no, it's not fixed" that routing has to
     * attribute. With no record of the question, there is nothing for the reply
     * to be an answer TO.
     *
     * Best-effort: the citizen already has the notification.
     */
    private void recordOnConversation(String ticketId, String channel, String body, String channelMessageId) {
        if (ticketId == null) {
            return;
        }
        try {
            Map<String, Object> message = new java.util.LinkedHashMap<>();
            message.put("channel", channel);
            message.put("direction", "outbound");
            message.put("authorType", "system");
            message.put("content", body);
            if (channelMessageId != null) {
                message.put("channelMessageId", channelMessageId);
            }
            DbWriterClient.ApiResult recorded = db.call(
                    "POST", "/api/v1/db/tickets/" + ticketId + "/messages", message);
            if (recorded.status() >= 400) {
                LOG.warnf("status-update notification sent but not recorded for ticket %s: %s",
                        ticketId, recorded.body());
            }
        } catch (Exception e) {
            LOG.warnf("status-update notification sent but not recorded for ticket %s: %s",
                    ticketId, e.getMessage());
        }
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
