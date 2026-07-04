package com.uniserve.auth;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Ticket API for the dashboard (Feature 11/12), RBAC-scoped and proxied to
 * db-writer. Agents may only see their own tickets; leads/admins see all.
 */
@Path("/api/v1/tickets")
@Produces(MediaType.APPLICATION_JSON)
public class TicketsResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @GET
    public Response list(@QueryParam("assignedTo") String assignedTo,
                         @QueryParam("status") String status,
                         @QueryParam("channel") String channel,
                         @QueryParam("category") String category,
                         @QueryParam("page") String page,
                         @QueryParam("pageSize") String pageSize) {
        String role = user.role();
        String resolvedAssignee = assignedTo;

        if ("agent".equals(role)) {
            if (!"me".equals(assignedTo)) {
                return forbidden("INSUFFICIENT_ROLE", "Agents can only view their assigned tickets");
            }
            resolvedAssignee = user.agentId();
        } else if ("me".equals(assignedTo)) {
            resolvedAssignee = user.agentId();
        } else if ("none".equals(assignedTo)) {
            resolvedAssignee = null; // unassigned filter not supported in Phase 1; return tenant list
        }

        StringBuilder q = new StringBuilder("tenantId=").append(enc(user.tenantId()));
        append(q, "assignedTo", "none".equals(assignedTo) ? null : resolvedAssignee);
        append(q, "status", status);
        append(q, "channel", channel);
        append(q, "category", category);
        append(q, "page", page);
        append(q, "pageSize", pageSize);

        List<Map<String, Object>> tickets = db.listTickets(q.toString());
        return Response.ok(Map.of("tickets", tickets, "total", tickets.size(), "page", 1)).build();
    }

    @GET
    @Path("/{id}")
    public Response detail(@PathParam("id") String id) {
        DbWriterClient.ApiResult ticket = db.call("GET", "/api/v1/db/tickets/" + id, null);
        if (ticket.status() >= 400) {
            return Response.status(ticket.status()).entity(ticket.body()).build();
        }
        Map<String, Object> t = ticket.body();
        List<Map<String, Object>> notes = new ArrayList<>();
        for (Map<String, Object> n : db.ticketNotes(id)) {
            Map<String, Object> note = new LinkedHashMap<>();
            note.put("authorType", n.getOrDefault("author_type", "agent"));
            note.put("authorLabel", n.getOrDefault("author_label", "Agent"));
            note.put("content", n.get("content"));
            note.put("createdAt", n.get("created_at"));
            notes.add(note);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", t.get("id"));
        body.put("ticketNumber", t.get("ticket_number"));
        body.put("status", t.get("status"));
        body.put("resolution", t.get("resolution"));
        body.put("category", t.get("category"));
        body.put("assignedTo", t.get("assigned_to"));
        body.put("notes", notes);
        return Response.ok(body).build();
    }

    @POST
    @Path("/{id}/transition")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response transition(@PathParam("id") String id, Map<String, Object> input) {
        DbWriterClient.ApiResult current = db.call("GET", "/api/v1/db/tickets/" + id, null);
        if (current.status() >= 400) {
            return Response.status(current.status()).entity(current.body()).build();
        }
        String fromStatus = String.valueOf(current.body().get("status"));
        String toStatus = str(input, "toStatus");
        if (!user.can(transitionAction(toStatus))) {
            return forbidden("INSUFFICIENT_ROLE", "Your role cannot perform this transition");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("fromStatus", fromStatus);
        body.put("toStatus", toStatus);
        body.put("noteContent", input.getOrDefault("note", input.get("noteContent")));
        body.put("agentId", user.agentId());

        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/" + id + "/transition", body);
        return Response.status(result.status()).entity(result.body()).build();
    }

    @POST
    @Path("/{id}/generate-resolution-summary")
    public Response resolutionSummary(@PathParam("id") String id) {
        DbWriterClient.ApiResult result =
                db.call("POST", "/api/v1/db/tickets/" + id + "/generate-resolution-summary", null);
        return Response.status(result.status()).entity(result.body()).build();
    }

    // ---- helpers ---------------------------------------------------------

    private static String transitionAction(String toStatus) {
        return switch (toStatus == null ? "" : toStatus) {
            case "assigned" -> "ticket.status.open_to_assigned";
            case "in_progress" -> "ticket.status.assigned_to_inprogress";
            case "resolved" -> "ticket.status.inprogress_to_resolved";
            case "closed" -> "ticket.status.resolved_to_closed";
            case "reopened" -> "ticket.status.closed_to_reopened";
            default -> "ticket.edit";
        };
    }

    private static void append(StringBuilder q, String key, String value) {
        if (value != null && !value.isBlank()) {
            q.append('&').append(key).append('=').append(enc(value));
        }
    }

    private static String enc(String v) {
        return URLEncoder.encode(v, StandardCharsets.UTF_8);
    }

    private Response forbidden(String code, String message) {
        return Response.status(403).entity(Map.of("error", Map.of("code", code, "message", message))).build();
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
