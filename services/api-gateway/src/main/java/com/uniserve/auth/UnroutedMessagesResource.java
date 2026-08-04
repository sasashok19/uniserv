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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The unrouted-message queue (Feature 24) — citizen messages routing could not
 * attribute to any ticket and deliberately did not invent one for.
 *
 * Lead/admin only (`unrouted.view` / `unrouted.manage`): resolving an entry
 * files a citizen's words onto a ticket of the agent's choosing, and an agent
 * who only sees their own tickets has no basis for that call.
 */
@Path("/api/v1/unrouted-messages")
@Produces(MediaType.APPLICATION_JSON)
public class UnroutedMessagesResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    /** Pending and escalated by default — that is the work, not the archive. */
    @GET
    public Response list(@QueryParam("status") String status,
                         @QueryParam("page") String page,
                         @QueryParam("pageSize") String pageSize) {
        if (!user.can("unrouted.view")) {
            return forbidden("Only leads and admins can view unrouted messages");
        }
        StringBuilder q = new StringBuilder("tenantId=").append(enc(user.tenantId()));
        q.append("&status=").append(enc(status == null || status.isBlank() ? "pending,escalated" : status));
        if (page != null && !page.isBlank()) {
            q.append("&page=").append(enc(page));
        }
        if (pageSize != null && !pageSize.isBlank()) {
            q.append("&pageSize=").append(enc(pageSize));
        }
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/unrouted-messages?" + q, null);
        if (result.status() >= 400) {
            return Response.status(result.status()).entity(result.body()).build();
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("messages", result.body() == null ? java.util.List.of() : result.body().get("data"));
        body.put("total", result.body() == null ? 0 : result.body().get("total"));
        return Response.ok(body).build();
    }

    /**
     * File this message against the ticket it belonged to. db-writer copies the
     * text onto that ticket's conversation as well as marking this entry
     * resolved — clearing the queue without delivering the message would defeat
     * the point of keeping it.
     */
    @POST
    @Path("/{id}/attach")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response attach(@PathParam("id") String id, Map<String, Object> input) {
        if (!user.can("unrouted.manage")) {
            return forbidden("Only leads and admins can resolve unrouted messages");
        }
        // A ticket NUMBER is what the agent is actually looking at, so it is
        // accepted and resolved here rather than making the UI hunt for a UUID.
        String ticketId = str(input, "ticketId");
        String ticketNumber = str(input, "ticketNumber");
        if (ticketId == null && ticketNumber != null) {
            List<Map<String, Object>> found = db.listTickets(
                    "tenantId=" + enc(user.tenantId()) + "&ticketNumber=" + enc(ticketNumber.trim()));
            if (found.isEmpty()) {
                return Response.status(404).entity(Map.of("error", Map.of(
                        "code", "TICKET_NOT_FOUND",
                        "message", "No ticket " + ticketNumber.trim() + " in this tenant"))).build();
            }
            Object resolved = found.get(0).get("id");
            ticketId = resolved == null ? null : String.valueOf(resolved);
        }
        if (ticketId == null || ticketId.isBlank()) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "TICKET_REQUIRED", "message", "ticketId or ticketNumber is required"))).build();
        }
        DbWriterClient.ApiResult result = db.call("POST",
                "/api/v1/db/unrouted-messages/" + id + "/attach",
                Map.of("ticketId", ticketId, "agentId", user.agentId()));
        return Response.status(result.status()).entity(result.body()).build();
    }

    /** Judge it noise. Kept as a row (status `discarded`), never deleted. */
    @POST
    @Path("/{id}/discard")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response discard(@PathParam("id") String id) {
        if (!user.can("unrouted.manage")) {
            return forbidden("Only leads and admins can resolve unrouted messages");
        }
        DbWriterClient.ApiResult result = db.call("POST",
                "/api/v1/db/unrouted-messages/" + id + "/discard",
                Map.of("agentId", user.agentId()));
        return Response.status(result.status()).entity(result.body()).build();
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        String s = v == null ? null : String.valueOf(v);
        return s == null || s.isBlank() ? null : s;
    }

    private static Response forbidden(String message) {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE", "message", message))).build();
    }

    private static String enc(String v) {
        return java.net.URLEncoder.encode(v == null ? "" : v, java.nio.charset.StandardCharsets.UTF_8);
    }
}
