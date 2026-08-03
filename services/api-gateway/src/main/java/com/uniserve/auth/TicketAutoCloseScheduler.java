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

    /**
     * `delayed` is the fix for a job that had never once succeeded in
     * production. Quarkus fires an `every` trigger IMMEDIATELY at startup, so
     * the first tick ran while the instance was still coming up — this app
     * takes ~23s to boot — and the outbound connection timed out before the
     * app was really serving. Because the instance restarts often, that
     * boot-time tick was in practice the ONLY tick that ever ran, so every
     * run failed and unconfirmed tickets were never swept. Observed as a
     * recurring `auto-close-unconfirmed call failed: status=502 ... HTTP
     * connect timed out` logged 3-6 seconds after each "started in 23.0s".
     *
     * Nothing here is time-critical — the job closes tickets that have been
     * idle for 14 days — so skipping the first two minutes costs nothing.
     */
    @Scheduled(every = "{ticket.auto-close.interval}", delayed = "{ticket.auto-close.startup-delay}")
    void run() {
        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/auto-close-unconfirmed",
                Map.of("olderThanDays", UNCONFIRMED_AUTO_CLOSE_DAYS));
        if (result.status() >= 400) {
            // 502/DB_WRITER_UNAVAILABLE here means db-writer could not be
            // reached at all. DbWriterClient already retries connect failures
            // (a suspended instance waking up is the usual cause on this
            // hourly tick), so reaching this line means it stayed unreachable.
            LOG.warnf("auto-close-unconfirmed call failed: status=%d body=%s — will retry on the next tick",
                    result.status(), result.body());
            return;
        }
        if (result.body() == null) {
            LOG.warn("auto-close-unconfirmed returned no body; skipping this tick");
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
                notifier.sendStatusUpdate(ticket, "closed", note);
            }
        }
    }
}
