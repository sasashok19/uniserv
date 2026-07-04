package com.uniserve.dbwriter.analytics;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.db.Db;
import jakarta.inject.Inject;
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
 * Analytics (Feature 04). PHASE_1 implements ticket volume by day/channel — the
 * tested endpoint. SLA / priority / per-agent analytics are added in later features.
 */
@Path("/api/v1/db/analytics")
@Produces(MediaType.APPLICATION_JSON)
public class AnalyticsResource {

    @Inject
    Db db;

    @GET
    @Path("/volume")
    public Map<String, Object> volume(@QueryParam("tenantId") String tenantId,
                                      @QueryParam("period") String period) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        int days = parseDays(period);
        String modifier = "-" + days + " days";

        List<Map<String, Object>> rows = db.query("""
                SELECT date(created_at) AS d, channel_origin AS channel, COUNT(*) AS c
                  FROM tickets
                 WHERE tenant_id = ? AND created_at >= datetime('now', ?)
                 GROUP BY d, channel_origin
                 ORDER BY d
                """, tenantId, modifier);

        // Fold (date, channel, count) rows into per-date entries with a byChannel map.
        Map<String, Map<String, Object>> byDate = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            String date = String.valueOf(row.get("d"));
            int count = ((Number) row.get("c")).intValue();
            String channel = row.get("channel") == null ? "unknown" : String.valueOf(row.get("channel"));

            Map<String, Object> entry = byDate.computeIfAbsent(date, d -> {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("date", d);
                e.put("day", d);   // alias — Feature 13 uses "day", Feature 04 uses "date"
                e.put("count", 0);
                e.put("byChannel", new LinkedHashMap<String, Integer>());
                return e;
            });
            entry.put("count", ((Number) entry.get("count")).intValue() + count);
            @SuppressWarnings("unchecked")
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
        Map<String, Object> row = db.queryOne("""
                SELECT
                  COUNT(CASE WHEN resolved_at IS NOT NULL AND resolved_at <= sla_due_at THEN 1 END) AS met,
                  COUNT(CASE WHEN (resolved_at IS NOT NULL AND resolved_at > sla_due_at)
                               OR (sla_due_at IS NOT NULL AND sla_due_at < datetime('now') AND resolved_at IS NULL)
                             THEN 1 END) AS breached,
                  COUNT(*) AS total
                FROM tickets
                WHERE tenant_id = ? AND created_at >= datetime('now', ?)
                """, tenantId, modifier).orElse(Map.of());

        int met = intOf(row.get("met"));
        int breached = intOf(row.get("breached"));
        int total = intOf(row.get("total"));
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
    public Map<String, Object> priority(@QueryParam("tenantId") String tenantId,
                                        @QueryParam("period") String period) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String modifier = "-" + parseDays(period) + " days";
        List<Map<String, Object>> rows = db.query("""
                SELECT priority_label AS label, COUNT(*) AS count
                  FROM tickets
                 WHERE tenant_id = ? AND created_at >= datetime('now', ?)
                 GROUP BY priority_label
                """, tenantId, modifier);
        Map<String, Object> dist = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            String label = row.get("label") == null ? "unlabelled" : String.valueOf(row.get("label"));
            dist.put(label, intOf(row.get("count")));
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
