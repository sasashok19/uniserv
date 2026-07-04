package com.uniserve.notifications;

/**
 * Notification message templates (Feature 14).
 *
 * <p>PHASE_1: rendered inline (subject + HTML body) per event type. The doc lists
 * Qute template files; those are a Phase-1 convenience and can replace this class
 * without changing the send path.
 */
public final class NotificationTemplates {

    private NotificationTemplates() {
    }

    public record Message(String subject, String body) {
    }

    public static Message build(String type, String ticketNumber, String category) {
        String tn = ticketNumber == null ? "your complaint" : ticketNumber;
        String cat = category == null ? "" : category;
        return switch (type == null ? "" : type) {
            case "ticket_created" -> new Message(
                    "Complaint " + tn + " registered",
                    "<p>Your complaint <strong>" + tn + "</strong> (" + cat
                            + ") has been registered. We'll keep you updated.</p>");
            case "ticket_resolved" -> new Message(
                    "Complaint " + tn + " resolved",
                    "<p>Your complaint <strong>" + tn + "</strong> has been resolved. "
                            + "Please reply if you need further help.</p>");
            case "critical_alert" -> new Message(
                    "⚠ Critical ticket " + tn,
                    "<p>A new <strong>critical</strong> ticket " + tn + " (" + cat
                            + ") requires attention.</p>");
            case "sla_warning" -> new Message(
                    "SLA breach imminent for " + tn,
                    "<p>Ticket " + tn + " is within 1 hour of its SLA deadline.</p>");
            case "ticket_reopened" -> new Message(
                    "Ticket " + tn + " reopened",
                    "<p>Ticket " + tn + " has been reopened and needs your attention.</p>");
            default -> new Message(
                    "UniServe notification",
                    "<p>Update regarding " + tn + ".</p>");
        };
    }
}
