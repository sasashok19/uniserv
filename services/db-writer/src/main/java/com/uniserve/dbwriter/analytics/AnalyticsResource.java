package com.uniserve.dbwriter.analytics;

import com.uniserve.dbwriter.common.ApiException;
import jakarta.inject.Inject;
import jakarta.persistence.EntityManager;
import jakarta.persistence.Query;
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
 * Analytics (Feature 04/13/15). Reporting/aggregate queries run as native SQL over
 * the Hibernate-managed {@link EntityManager} — the idiomatic way to do GROUP BY
 * style reporting in a Panache app, since these aren't single-entity CRUD reads.
 *
 * <p>Every endpoint accepts the same optional filter set (agent, citizen/identity,
 * category, priority) on top of the tenant + rolling-{@code period} window, and
 * excludes soft-deleted (archived) tickets.
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
                                      @QueryParam("period") String period,
                                      @QueryParam("agentId") String agentId,
                                      @QueryParam("identityId") String identityId,
                                      @QueryParam("category") String category,
                                      @QueryParam("priorityLabel") String priorityLabel) {
        requireTenant(tenantId);
        Filters f = buildFilters(agentId, identityId, category, priorityLabel, 3);
        Query query = em.createNativeQuery("""
                SELECT date(created_at) AS d, channel_origin AS channel, COUNT(*) AS c
                  FROM tickets
                 WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2) AND archived_at IS NULL
                """ + f.sql() + """
                 GROUP BY d, channel_origin
                 ORDER BY d
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier(period));
        f.bind(query);
        List<Object[]> rows = query.getResultList();

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
                                   @QueryParam("period") String period,
                                   @QueryParam("agentId") String agentId,
                                   @QueryParam("identityId") String identityId,
                                   @QueryParam("category") String category,
                                   @QueryParam("priorityLabel") String priorityLabel) {
        requireTenant(tenantId);
        Filters f = buildFilters(agentId, identityId, category, priorityLabel, 3);
        Query query = em.createNativeQuery("""
                SELECT
                  COUNT(CASE WHEN resolved_at IS NOT NULL AND resolved_at <= sla_due_at THEN 1 END) AS met,
                  COUNT(CASE WHEN (resolved_at IS NOT NULL AND resolved_at > sla_due_at)
                               OR (sla_due_at IS NOT NULL AND sla_due_at < datetime('now') AND resolved_at IS NULL)
                             THEN 1 END) AS breached,
                  COUNT(*) AS total
                FROM tickets
                WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2) AND archived_at IS NULL
                """ + f.sql())
                .setParameter(1, tenantId)
                .setParameter(2, modifier(period));
        f.bind(query);
        Object[] row = (Object[]) query.getSingleResult();

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
                                        @QueryParam("period") String period,
                                        @QueryParam("agentId") String agentId,
                                        @QueryParam("identityId") String identityId,
                                        @QueryParam("category") String category,
                                        @QueryParam("priorityLabel") String priorityLabel) {
        requireTenant(tenantId);
        Filters f = buildFilters(agentId, identityId, category, priorityLabel, 3);
        Query query = em.createNativeQuery("""
                SELECT priority_label AS label, COUNT(*) AS count
                  FROM tickets
                 WHERE tenant_id = ?1 AND created_at >= datetime('now', ?2) AND archived_at IS NULL
                """ + f.sql() + """
                 GROUP BY priority_label
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier(period));
        f.bind(query);
        List<Object[]> rows = query.getResultList();
        Map<String, Object> dist = new LinkedHashMap<>();
        for (Object[] row : rows) {
            String label = row[0] == null ? "unlabelled" : String.valueOf(row[0]);
            dist.put(label, intOf(row[1]));
        }
        return Map.of("data", dist);
    }

    /** Agent performance (Feature 13, Lead/Admin only — enforced by the gateway):
     * resolved-ticket count and average resolution time per agent. */
    @GET
    @Path("/agents")
    @SuppressWarnings("unchecked")
    public Map<String, Object> agents(@QueryParam("tenantId") String tenantId,
                                      @QueryParam("period") String period,
                                      @QueryParam("agentId") String agentId,
                                      @QueryParam("identityId") String identityId,
                                      @QueryParam("category") String category,
                                      @QueryParam("priorityLabel") String priorityLabel) {
        requireTenant(tenantId);
        Filters f = buildFilters(agentId, identityId, category, priorityLabel, 3);
        Query query = em.createNativeQuery("""
                SELECT a.id AS agent_id, a.name AS agent_name, COUNT(t.id) AS resolved,
                       AVG(JULIANDAY(t.resolved_at) - JULIANDAY(t.created_at)) * 24 AS avg_hours
                  FROM tickets t
                  JOIN agents a ON t.assigned_to = a.id
                 WHERE t.tenant_id = ?1 AND t.created_at >= datetime('now', ?2)
                   AND t.archived_at IS NULL AND t.resolved_at IS NOT NULL
                """ + f.sql() + """
                 GROUP BY a.id, a.name
                 ORDER BY resolved DESC
                """)
                .setParameter(1, tenantId)
                .setParameter(2, modifier(period));
        f.bind(query);
        List<Object[]> rows = query.getResultList();
        List<Map<String, Object>> data = new ArrayList<>();
        for (Object[] row : rows) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("agentId", row[0]);
            entry.put("agentName", row[1]);
            entry.put("resolved", intOf(row[2]));
            entry.put("avgResolutionHours", row[3] == null ? null : Math.round(((Number) row[3]).doubleValue() * 10) / 10.0);
            data.add(entry);
        }
        return Map.of("data", data);
    }

    private static void requireTenant(String tenantId) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
    }

    private static int intOf(Object v) {
        return v instanceof Number n ? n.intValue() : 0;
    }

    private String modifier(String period) {
        return "-" + parseDays(period) + " days";
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

    /** Builds the optional `AND col = ?n` fragments shared by every endpoint above. */
    private static Filters buildFilters(String agentId, String identityId, String category,
                                        String priorityLabel, int startIndex) {
        StringBuilder sql = new StringBuilder();
        List<Object> params = new ArrayList<>();
        int idx = startIndex;
        if (agentId != null && !agentId.isBlank()) {
            sql.append(" AND assigned_to = ?").append(idx++);
            params.add(agentId);
        }
        if (identityId != null && !identityId.isBlank()) {
            sql.append(" AND identity_id = ?").append(idx++);
            params.add(identityId);
        }
        if (category != null && !category.isBlank()) {
            sql.append(" AND category = ?").append(idx++);
            params.add(category);
        }
        if (priorityLabel != null && !priorityLabel.isBlank()) {
            sql.append(" AND priority_label = ?").append(idx++);
            params.add(priorityLabel);
        }
        return new Filters(sql.toString(), params, startIndex);
    }

    private record Filters(String sql, List<Object> params, int startIndex) {
        void bind(Query query) {
            for (int i = 0; i < params.size(); i++) {
                query.setParameter(startIndex + i, params.get(i));
            }
        }
    }
}
