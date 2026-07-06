package com.uniserve.dbwriter.analytics;

import com.uniserve.dbwriter.common.ApiException;
import jakarta.inject.Inject;
import jakarta.persistence.EntityManager;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Analytics (Feature 04/13). Reporting/aggregate queries run as native SQL over
 * the Hibernate-managed {@link EntityManager} — the idiomatic way to do GROUP BY
 * style reporting in a Panache app, since these aren't single-entity CRUD reads.
 */
@Path("/api/v1/db/analytics")
@Produces(MediaType.APPLICATION_JSON)
public class AnalyticsResource {

    @Inject
    EntityManager em;

    @GET
    @Path("/volume")
    @SuppressWarnings("unchecked")
    public Map<String, Object> volume(@QueryParam("tenantId") String tenantId,
                                      @QueryParam("period") String period) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String modifier = "-" + parseDays(period) + " days";

        List<Object[]> rows = em.createNativeQuery("""
                SELECT date(created_at) AS d, channel_origin AS channel, COUNT(*) AS c
                  FROM tickets
                 WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2)
                 GROUP BY d, channel_origin
                 ORDER BY d
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier)
                .getResultList();

        // Fold (date, channel, count) rows into per-date entries with a byChannel map.
        Map<String, Map<String, Object>> byDate = new LinkedHashMap<>();
        for (Object[] row : rows) {
            String date = String.valueOf(row[0]);
            String channel = row[1] == null ? "unknown" : String.valueOf(row[1]);
            int count = ((Number) row[2]).intValue();

            Map<String, Object> entry = byDate.computeIfAbsent(date, d -> {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("date", d);
                e.put("day", d);   // alias — Feature 13 uses "day", Feature 04 uses "date"
                e.put("count", 0);
                e.put("byChannel", new LinkedHashMap<String, Integer>());
                return e;
            });
            entry.put("count", ((Number) entry.get("count")).intValue() + count);
            Map<String, Integer> byChannel = (Map<String, Integer>) entry.get("byChannel");
            byChannel.merge(channel, count, Integer::sum);
        }

        return Map.of("data", new ArrayList<>(byDate.values()));
    }

    @GET
    @Path("/sla")
    public Map<String, Object> sla(@QueryParam("tenantId") String tenantId,
                                   @QueryParam("period") String period) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String modifier = "-" + parseDays(period) + " days";
        Object[] row = (Object[]) em.createNativeQuery("""
                SELECT
                  COUNT(CASE WHEN resolved_at IS NOT NULL AND resolved_at <= sla_due_at THEN 1 END) AS met,
                  COUNT(CASE WHEN (resolved_at IS NOT NULL AND resolved_at > sla_due_at)
                               OR (sla_due_at IS NOT NULL AND sla_due_at < datetime('now') AND resolved_at IS NULL)
                             THEN 1 END) AS breached,
                  COUNT(*) AS total
                FROM tickets
                WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2)
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier)
                .getSingleResult();

        int met = intOf(row[0]);
        int breached = intOf(row[1]);
        int total = intOf(row[2]);
        double pct = total == 0 ? 0.0 : Math.round((met * 1000.0 / total)) / 10.0;

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("met", met);
        body.put("breached", breached);
        body.put("total", total);
        body.put("slaMetPercent", pct);
        return body;
    }

    @GET
    @Path("/priority")
    @SuppressWarnings("unchecked")
    public Map<String, Object> priority(@QueryParam("tenantId") String tenantId,
                                        @QueryParam("period") String period) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String modifier = "-" + parseDays(period) + " days";
        List<Object[]> rows = em.createNativeQuery("""
                SELECT priority_label AS label, COUNT(*) AS count
                  FROM tickets
                 WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2)
                 GROUP BY priority_label
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier)
                .getResultList();
        Map<String, Object> dist = new LinkedHashMap<>();
        for (Object[] row : rows) {
            String label = row[0] == null ? "unlabelled" : String.valueOf(row[0]);
            dist.put(label, intOf(row[1]));
        }
        return Map.of("data", dist);
    }

    private static int intOf(Object v) {
        return v instanceof Number n ? n.intValue() : 0;
    }

    private int parseDays(String period) {
        if (period == null || period.isBlank()) {
            return 30;
        }
        String digits = period.replaceAll("[^0-9]", "");
        if (digits.isEmpty()) {
            return 30;
        }
        return Integer.parseInt(digits);
    }
}
