package com.uniserve.auth;

import io.quarkus.scheduler.Scheduled;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

import java.util.List;
import java.util.Map;

/**
 * Feature 06 x 14: a ticket still awaiting identity confirmation ({@code
 * identityStatus=pending}) with no citizen response for 14 days is
 * automatically closed — distinct from the admin-triggered 60-day
 * archive-stale cleanup, which soft-deletes rather than closing. Citizens
 * are notified via the same structured status-update email as a manual
 * resolve/close transition.
 */
@ApplicationScoped
public class TicketAutoCloseScheduler {

    private static final Logger LOG = Logger.getLogger(TicketAutoCloseScheduler.class);
    private static final int UNCONFIRMED_AUTO_CLOSE_DAYS = 14;

    @Inject
    DbWriterClient db;

    @Inject
    TicketNotifier notifier;

    @Scheduled(every = "{ticket.auto-close.interval}")
    void run() {
        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/auto-close-unconfirmed",
                Map.of("olderThanDays", UNCONFIRMED_AUTO_CLOSE_DAYS));
        if (result.status() >= 400) {
            LOG.warnf("auto-close-unconfirmed call failed: status=%d body=%s", result.status(), result.body());
            return;
        }
        Object closedObj = result.body().get("closed");
        if (!(closedObj instanceof List<?> closed) || closed.isEmpty()) {
            return;
        }
        LOG.infof("auto-closed %d unconfirmed ticket(s) after %d days", closed.size(), UNCONFIRMED_AUTO_CLOSE_DAYS);
        String note = "Automatically closed after " + UNCONFIRMED_AUTO_CLOSE_DAYS
                + " days with no response to our identity verification request.";
        for (Object o : closed) {
            if (o instanceof Map<?, ?> raw) {
                @SuppressWarnings("unchecked")
                Map<String, Object> ticket = (Map<String, Object>) raw;
                notifier.sendStatusUpdateEmail(ticket, "closed", note);
            }
        }
    }
}
