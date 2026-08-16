package com.uniserve.dbwriter.admin;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.TicketEvent;
import com.uniserve.dbwriter.tickets.TicketCache;
import io.quarkus.hibernate.orm.panache.Panache;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.transaction.Transactional;
import org.jboss.logging.Logger;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Tenant data reset (UI_REVAMP_v2 Feature D) — deletes every ticket, identity,
 * note, message, event, unrouted message and announcement for ONE tenant,
 * preserving the tenants row, the calling admin's agents row and the seeded
 * staff accounts ({@link #SEED_AGENT_IDS}). Deliberately dangerous, so wrapped in
 * layered safeguards: the gateway has already verified admin role + re-entered
 * password + the typed "RESET" confirmation before this is ever called; here we
 * re-require the confirmation value and rate-limit to one reset per tenant per
 * 60 seconds.
 *
 * <p><b>Configuration is never touched.</b> Everything under the tenant's
 * {@code config_json} — the WhatsApp menu copy, landing page, intake fields,
 * categories, SLA and news settings — survives a reset exactly as configured.
 * This clears a tenant's DATA; it is not a factory reset of its setup, and it
 * does not restore defaults over wording an admin has tuned.
 *
 * <p>Audit: the intent is logged at WARN <em>before</em> any delete executes,
 * and a {@code tenant.reset} ticket-event row (synthetic ticket id) is written
 * <em>after</em> the deletes inside the same transaction — writing it first, as
 * originally spec'd, would be self-defeating since the sequence deletes the
 * tenant's ticket_events. Row counts per table are recorded in {@code meta_json}.
 */
@ApplicationScoped
public class AdminResetService {

    private static final Logger LOG = Logger.getLogger(AdminResetService.class);
    private static final long RATE_LIMIT_MS = 60_000;

    /** tenantId -> last reset epoch millis (single-instance Phase 1 is fine). */
    private final ConcurrentHashMap<String, Long> lastReset = new ConcurrentHashMap<>();

    @Inject
    TicketCache cache;

    /** Tables deleted, in dependency order. Agents are handled separately.
     *
     * <p>{@code unrouted_messages} was missing until it was noticed that the
     * Unrouted queue survived a reset — and survived it holding
     * {@code resolved_ticket_id} and {@code resolved_by} pointing at rows that
     * had just been deleted. It goes first: it references both tickets and
     * agents. */
    private static final List<String> TENANT_TABLES = List.of(
            "unrouted_messages", "ticket_events", "ticket_notes", "ticket_messages", "tickets",
            "identity_profiles", "identity_pending_queue", "announcements");

    /**
     * The staff accounts that ship with the product (the {@code V3} seed), kept
     * by a reset alongside the admin who asked for it.
     *
     * <p>They used to be deleted, and nothing brought them back: {@code V3} is
     * {@code INSERT OR IGNORE} and Flyway will not re-run an applied migration,
     * so "reset" permanently removed the Lead and Field agents an admin needs to
     * demo or test the role-based views. A reset is meant to clear the tenant's
     * DATA, not dismantle its staff.
     *
     * <p>Seeded citizen identities are deliberately NOT preserved: those are
     * data, they arrive again the moment anyone messages in, and a stale demo
     * citizen in a freshly reset tenant is clutter.
     */
    static final List<String> SEED_AGENT_IDS = List.of("a1", "a2", "a3");

    public Map<String, Object> reset(String tenantId, String adminAgentId, String confirmation) {
        if (!"RESET".equals(confirmation)) {
            throw new ApiException(400, "CONFIRMATION_REQUIRED", "confirmation must be exactly RESET");
        }
        long now = System.currentTimeMillis();
        Long last = lastReset.get(tenantId);
        if (last != null && now - last < RATE_LIMIT_MS) {
            long retryAfter = (RATE_LIMIT_MS - (now - last) + 999) / 1000;
            throw new ApiException(429, "RATE_LIMITED", "retry after " + retryAfter + " seconds");
        }

        LOG.warnf("TENANT RESET starting: tenantId=%s requestedBy=%s", tenantId, adminAgentId);
        Map<String, Object> counts = doReset(tenantId, adminAgentId, SEED_AGENT_IDS);
        // Stamp the rate limit only AFTER success — a failed/rolled-back attempt
        // shouldn't lock the admin out for 60s.
        lastReset.put(tenantId, now);
        cache.invalidateAll();
        LOG.warnf("TENANT RESET complete: tenantId=%s deleted=%s", tenantId, counts);
        return counts;
    }

    /**
     * @param preservedAgentIds staff accounts to keep in addition to the caller.
     *                          A parameter rather than a direct read of
     *                          {@link #SEED_AGENT_IDS} so a test can prove the
     *                          rule on a throwaway tenant: agent ids are the
     *                          primary key, so a test cannot create its own
     *                          "a2" to reset alongside the real one.
     */
    @Transactional
    Map<String, Object> doReset(String tenantId, String adminAgentId, List<String> preservedAgentIds) {
        var em = Panache.getEntityManager();
        Map<String, Object> counts = new LinkedHashMap<>();
        for (String table : TENANT_TABLES) {
            int deleted = em.createNativeQuery("delete from " + table + " where tenant_id = :t")
                    .setParameter("t", tenantId)
                    .executeUpdate();
            counts.put(table, deleted);
        }
        // The caller is always kept; an empty preserved list would otherwise
        // make `not in ()` invalid SQL, so it is folded into one set.
        List<String> keep = new java.util.ArrayList<>(preservedAgentIds == null ? List.of() : preservedAgentIds);
        keep.add(adminAgentId);
        int agents = em.createNativeQuery("delete from agents where tenant_id = :t and id not in (:keep)")
                .setParameter("t", tenantId)
                .setParameter("keep", keep)
                .executeUpdate();
        counts.put("agents", agents);

        // Audit row — written after the deletes (same transaction) so it survives
        // the ticket_events wipe. Synthetic ticket id: this event is about the
        // tenant, not any one ticket (FKs are not enforced by the sqlite JDBC URL).
        TicketEvent audit = new TicketEvent();
        audit.id = UUID.randomUUID().toString();
        audit.tenantId = tenantId;
        audit.ticketId = "tenant-reset-" + UUID.randomUUID();
        audit.eventType = "tenant.reset";
        // ticket_events CHECKs actor_type IN ('system','ai','agent') — the admin
        // is an agents-table row, so 'agent' + actor_id identifies them precisely.
        audit.actorType = "agent";
        audit.actorId = adminAgentId;
        audit.metaJson = toJson(counts);
        audit.persist();
        return counts;
    }

    private static String toJson(Map<String, Object> counts) {
        StringBuilder sb = new StringBuilder("{");
        counts.forEach((k, v) -> sb.append('"').append(k).append("\":").append(v).append(','));
        if (sb.charAt(sb.length() - 1) == ',') {
            sb.setLength(sb.length() - 1);
        }
        return sb.append('}').toString();
    }
}
