package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PATCH;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.jboss.logging.Logger;

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

    private static final Logger LOG = Logger.getLogger(TicketsResource.class);

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @Inject
    EmailAdapter emailAdapter;

    @Inject
    TicketNotifier notifier;

    @GET
    public Response list(@QueryParam("assignedTo") String assignedTo,
                         @QueryParam("status") String status,
                         @QueryParam("channel") String channel,
                         @QueryParam("category") String category,
                         @QueryParam("identityStatus") String identityStatus,
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
        // Unconfirmed queue (Feature 12): ?identityStatus=pending,anonymous. Main
        // Ticket Queue passes identityStatus=confirmed so the two never overlap.
        append(q, "identityStatus", identityStatus);
        append(q, "page", page);
        append(q, "pageSize", pageSize);

        List<Map<String, Object>> tickets = db.listTickets(q.toString());
        Map<String, String> agentNames = agentDirectory();
        for (Map<String, Object> t : tickets) {
            String assignedAgentId = str(t, "assigned_to");
            t.put("assigned_to_name", assignedAgentId == null ? null : agentNames.get(assignedAgentId));
        }
        return Response.ok(Map.of("tickets", tickets, "total", tickets.size(), "page", 1)).build();
    }

    /** Lead/Admin only — reassign (or unassign, with a null/blank body value) a ticket. */
    @PATCH
    @Path("/{id}/assign")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response assign(@PathParam("id") String id, Map<String, Object> input) {
        if (!user.can("ticket.assignee.edit")) {
            return forbidden("INSUFFICIENT_ROLE", "Only leads and admins can assign tickets");
        }
        String assignedTo = input == null ? null : str(input, "assignedTo");
        Map<String, Object> patch = new LinkedHashMap<>();
        patch.put("assignedTo", (assignedTo == null || assignedTo.isBlank()) ? null : assignedTo);
        DbWriterClient.ApiResult result = db.call("PATCH", "/api/v1/db/tickets/" + id, patch);
        return Response.status(result.status()).entity(result.body()).build();
    }

    /** id -> name for every agent/lead/admin in the tenant, for the assign-to dropdown and queue display. */
    private Map<String, String> agentDirectory() {
        Map<String, String> names = new LinkedHashMap<>();
        for (Map<String, Object> a : db.listAgents(user.tenantId())) {
            names.put(str(a, "id"), str(a, "name"));
        }
        return names;
    }

    /** Admin-only: archive (soft-delete) unconfirmed tickets older than N days (default 60). */
    @POST
    @Path("/archive-stale")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response archiveStale(Map<String, Object> input) {
        if (!user.can("admin.tickets.archive-stale")) {
            return forbidden("INSUFFICIENT_ROLE", "Only admins can archive stale unconfirmed tickets");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tenantId", user.tenantId());
        body.put("olderThanDays", input == null ? 60 : input.getOrDefault("olderThanDays", 60));
        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/archive-stale", body);
        return Response.status(result.status()).entity(result.body()).build();
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
        List<Map<String, Object>> messages = new ArrayList<>();
        DbWriterClient.ApiResult msgResult = db.call("GET", "/api/v1/db/tickets/" + id + "/messages", null);
        if (msgResult.status() < 400) {
            Object rawMessages = msgResult.body().get("data");
            if (rawMessages instanceof List<?> list) {
                for (Object m : list) {
                    if (m instanceof Map<?, ?> mm) {
                        Map<String, Object> msg = new LinkedHashMap<>();
                        msg.put("direction", mm.get("direction"));
                        msg.put("authorType", mm.get("author_type"));
                        msg.put("content", mm.get("content"));
                        msg.put("createdAt", mm.get("created_at"));
                        messages.add(msg);
                    }
                }
            }
        }
        String identityId = str(t, "identity_id");
        String citizenName = null;
        String citizenEmail = null;
        String citizenPhone = null;
        if (identityId != null) {
            DbWriterClient.ApiResult identity = db.call("GET", "/api/v1/db/identities/" + identityId, null);
            if (identity.status() < 400) {
                citizenName = str(identity.body(), "name");
                citizenEmail = str(identity.body(), "email");
                citizenPhone = str(identity.body(), "phone");
            }
        }

        String serviceId = str(t, "service_id");
        if (serviceId == null && !messages.isEmpty()) {
            Object firstContent = messages.get(0).get("content");
            serviceId = extractServiceId(firstContent == null ? null : String.valueOf(firstContent));
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", t.get("id"));
        body.put("ticketNumber", t.get("ticket_number"));
        body.put("status", t.get("status"));
        body.put("resolution", t.get("resolution"));
        body.put("category", t.get("category"));
        body.put("channelOrigin", t.get("channel_origin"));
        body.put("identityId", identityId);
        body.put("citizenName", citizenName);
        body.put("citizenEmail", citizenEmail);
        body.put("citizenPhone", citizenPhone);
        body.put("serviceId", serviceId);
        body.put("priorityLabel", t.get("priority_label"));
        String assignedTo = str(t, "assigned_to");
        body.put("assignedTo", assignedTo);
        body.put("assignedToName", assignedTo == null ? null : agentDirectory().get(assignedTo));
        body.put("canAssign", user.can("ticket.assignee.edit"));
        body.put("notes", notes);
        body.put("messages", messages);
        return Response.ok(body).build();
    }

    @GET
    @Path("/{id}/notes")
    public Response listNotes(@PathParam("id") String id) {
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets/" + id + "/notes", null);
        return Response.status(result.status()).entity(result.body()).build();
    }

    @POST
    @Path("/{id}/notes")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response addNote(@PathParam("id") String id, Map<String, Object> input) {
        String content = str(input, "content");
        if (content == null || content.isBlank()) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "NOTE_EMPTY", "message", "Note content is required"))).build();
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", content);
        body.put("agentId", user.agentId());
        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/" + id + "/notes", body);
        return Response.status(result.status()).entity(result.body()).build();
    }

    /**
     * Send an update to the citizen (Feature 12/14): records an outbound
     * {@code ticket_messages} entry, and — for email-origin tickets — actually
     * sends it via {@link EmailAdapter#sendReply}. Other channels record the
     * message but have no outbound send wired yet (WhatsApp Business outbound
     * send is Phase 2).
     */
    @POST
    @Path("/{id}/reply")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response reply(@PathParam("id") String id, Map<String, Object> input) {
        String content = str(input, "content");
        if (content == null || content.isBlank()) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "REPLY_EMPTY", "message", "Reply content is required"))).build();
        }

        DbWriterClient.ApiResult ticket = db.call("GET", "/api/v1/db/tickets/" + id, null);
        if (ticket.status() >= 400) {
            return Response.status(ticket.status()).entity(ticket.body()).build();
        }
        Map<String, Object> t = ticket.body();
        String channel = str(t, "channel_origin");
        String identityId = str(t, "identity_id");
        String ticketNumber = str(t, "ticket_number");
        String originMessageId = str(t, "origin_message_id");

        Map<String, Object> messageBody = new LinkedHashMap<>();
        messageBody.put("channel", channel);
        messageBody.put("direction", "outbound");
        messageBody.put("authorType", "agent");
        messageBody.put("authorId", user.agentId());
        messageBody.put("content", content);
        DbWriterClient.ApiResult recorded = db.call(
                "POST", "/api/v1/db/tickets/" + id + "/messages", messageBody);
        if (recorded.status() >= 400) {
            return Response.status(recorded.status()).entity(recorded.body()).build();
        }

        boolean emailSent = false;
        String emailError = null;
        if ("email".equals(channel) && identityId != null) {
            DbWriterClient.ApiResult identity = db.call("GET", "/api/v1/db/identities/" + identityId, null);
            String toAddress = identity.status() < 400 ? str(identity.body(), "email") : null;
            if (toAddress != null && !toAddress.isBlank()) {
                try {
                    emailSent = emailAdapter.sendReply(
                            toAddress, "Update on your complaint " + ticketNumber, content, originMessageId);
                } catch (Exception e) {
                    emailError = e.getMessage();
                    LOG.errorf(e, "Failed to send reply email for ticket %s", id);
                }
            } else {
                emailError = "No email address on file for this ticket's identity";
            }
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("recorded", true);
        response.put("channel", channel);
        response.put("emailSent", emailSent);
        if (emailError != null) {
            response.put("emailError", emailError);
        }
        return Response.ok(response).build();
    }

    @POST
    @Path("/{id}/transition")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response transition(@PathParam("id") String id, Map<String, Object> input) {
        DbWriterClient.ApiResult current = db.call("GET", "/api/v1/db/tickets/" + id, null);
        if (current.status() >= 400) {
            return Response.status(current.status()).entity(current.body()).build();
        }
        Map<String, Object> ticket = current.body();
        String fromStatus = String.valueOf(ticket.get("status"));
        String toStatus = str(input, "toStatus");
        if (!user.can(transitionAction(toStatus))) {
            return forbidden("INSUFFICIENT_ROLE", "Your role cannot perform this transition");
        }
        String noteContent = str(input, "note");
        if (noteContent == null) {
            noteContent = str(input, "noteContent");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("fromStatus", fromStatus);
        body.put("toStatus", toStatus);
        body.put("noteContent", noteContent);
        body.put("agentId", user.agentId());

        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/tickets/" + id + "/transition", body);
        // Structured citizen-facing email (Feature 06 x 14): only on the
        // transitions the citizen actually cares about — resolved/closed —
        // not on every intermediate status change or standalone note.
        if (result.status() < 400 && ("resolved".equals(toStatus) || "closed".equals(toStatus))) {
            notifier.sendStatusUpdateEmail(ticket, toStatus, noteContent);
        }
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

    private static final java.util.regex.Pattern SERVICE_ID_RE =
            java.util.regex.Pattern.compile("Service/Customer ID:\\s*(.+)");

    /** Fallback for tickets created before the {@code service_id} column existed
     * (Feature 12/15) — the value was only ever embedded as text in the first message. */
    private static String extractServiceId(String firstMessageContent) {
        if (firstMessageContent == null) {
            return null;
        }
        java.util.regex.Matcher m = SERVICE_ID_RE.matcher(firstMessageContent);
        return m.find() ? m.group(1).trim() : null;
    }

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
