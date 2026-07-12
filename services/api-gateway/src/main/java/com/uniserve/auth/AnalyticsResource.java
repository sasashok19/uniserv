package com.uniserve.auth;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * Analytics (Feature 13/15), RBAC-scoped and proxied to db-writer. Any role
 * may view analytics, but only lead/admin may filter by an agent other than
 * themselves — a plain agent's {@code agentId} is always forced to their own
 * id, mirroring the {@code assignedTo=me} pattern in {@link TicketsResource}.
 */
@Path("/api/v1/analytics")
@Produces(MediaType.APPLICATION_JSON)
public class AnalyticsResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @GET
    @Path("/volume")
    public Response volume(@QueryParam("period") String period,
                           @QueryParam("agentId") String agentId,
                           @QueryParam("identityId") String identityId,
                           @QueryParam("category") String category,
                           @QueryParam("priorityLabel") String priorityLabel) {
        return proxy("volume", period, agentId, identityId, category, priorityLabel);
    }

    @GET
    @Path("/sla")
    public Response sla(@QueryParam("period") String period,
                        @QueryParam("agentId") String agentId,
                        @QueryParam("identityId") String identityId,
                        @QueryParam("category") String category,
                        @QueryParam("priorityLabel") String priorityLabel) {
        return proxy("sla", period, agentId, identityId, category, priorityLabel);
    }

    @GET
    @Path("/priority")
    public Response priority(@QueryParam("period") String period,
                             @QueryParam("agentId") String agentId,
                             @QueryParam("identityId") String identityId,
                             @QueryParam("category") String category,
                             @QueryParam("priorityLabel") String priorityLabel) {
        return proxy("priority", period, agentId, identityId, category, priorityLabel);
    }

    /** Lead/Admin only — per-agent resolved counts and average resolution time. */
    @GET
    @Path("/agents")
    public Response agents(@QueryParam("period") String period,
                           @QueryParam("agentId") String agentId,
                           @QueryParam("identityId") String identityId,
                           @QueryParam("category") String category,
                           @QueryParam("priorityLabel") String priorityLabel) {
        if (!user.can("analytics.view.all")) {
            return forbidden("Only leads and admins can view agent performance");
        }
        return proxy("agents", period, agentId, identityId, category, priorityLabel);
    }

    /** Lead/Admin only — minimal {id, name} list to populate the "by agent" filter dropdown
     * (the full agent-management list is admin-only; this is a narrower, read-only view). */
    @GET
    @Path("/agents-directory")
    public Response agentsDirectory() {
        if (!user.can("analytics.view.all")) {
            return forbidden("Only leads and admins can filter by agent");
        }
        List<Map<String, Object>> agents = db.listAgents(user.tenantId()).stream()
                .map(a -> (Map<String, Object>) Map.of("id", a.get("id"), "name", a.get("name")))
                .toList();
        return Response.ok(Map.of("agents", agents)).build();
    }

    /** Typeahead for the "by customer" filter. */
    @GET
    @Path("/customers")
    public Response customers(@QueryParam("q") String q) {
        if (!user.can("analytics.view")) {
            return forbidden("Not permitted to search citizens");
        }
        if (q == null || q.isBlank()) {
            return Response.ok(Map.of("customers", List.of())).build();
        }
        DbWriterClient.ApiResult result = db.call("GET",
                "/api/v1/db/identities?tenantId=" + enc(user.tenantId()) + "&q=" + enc(q), null);
        if (result.status() >= 400) {
            return Response.status(result.status()).entity(result.body()).build();
        }
        return Response.ok(Map.of("customers", castList(result.body().get("data")))).build();
    }

    private Response proxy(String metric, String period, String agentId, String identityId,
                           String category, String priorityLabel) {
        if (!user.can("analytics.view")) {
            return forbidden("Not permitted to view analytics");
        }
        boolean canViewAll = user.can("analytics.view.all");
        String effectiveAgentId = canViewAll ? agentId : user.agentId();

        StringBuilder q = new StringBuilder("tenantId=").append(enc(user.tenantId()));
        append(q, "period", period);
        append(q, "agentId", effectiveAgentId);
        append(q, "identityId", identityId);
        append(q, "category", category);
        append(q, "priorityLabel", priorityLabel);

        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/analytics/" + metric + "?" + q, null);
        return Response.status(result.status()).entity(result.body()).build();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> castList(Object v) {
        return v instanceof List<?> list ? (List<Map<String, Object>>) list : List.of();
    }

    private static void append(StringBuilder q, String key, String value) {
        if (value != null && !value.isBlank()) {
            q.append('&').append(key).append('=').append(enc(value));
        }
    }

    private static String enc(String v) {
        return URLEncoder.encode(v, StandardCharsets.UTF_8);
    }

    private Response forbidden(String message) {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE", "message", message))).build();
    }
}
