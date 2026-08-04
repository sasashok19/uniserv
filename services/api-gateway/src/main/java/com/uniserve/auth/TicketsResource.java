package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import com.uniserve.adapters.whatsapp.WhatsAppAdapter;
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
    WhatsAppAdapter whatsAppAdapter;

    @Inject
    TicketNotifier notifier;

    @GET
    public Response list(@QueryParam("assignedTo") String assignedTo,
                         @QueryParam("status") String status,
                         @QueryParam("channel") String channel,
                         @QueryParam("category") String category,
                         @QueryParam("identityStatus") String identityStatus,
                         @QueryParam("page") String page,
                         @QueryParam("pageSize") String pageSize,
                         @QueryParam("sortBy") String sortBy,
                         @QueryParam("sortDir") String sortDir) {
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
        append(q, "sortBy", sortBy);
        append(q, "sortDir", sortDir);

        // Use the raw call so we can surface db-writer's FULL matching count
        // (`total`) for pagination — `listTickets` only returns the page's rows.
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets?" + q, null);
        Object rawData = result.body() == null ? null : result.body().get("data");
        List<Map<String, Object>> tickets = new ArrayList<>();
        if (rawData instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> mm) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> t = (Map<String, Object>) mm;
                    tickets.add(t);
                }
            }
        }
        Object total = result.body() == null ? null : result.body().get("total");
        Map<String, String> agentNames = agentDirectory();
        for (Map<String, Object> t : tickets) {
            String assignedAgentId = str(t, "assigned_to");
            t.put("assigned_to_name", assignedAgentId == null ? null : agentNames.get(assignedAgentId));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tickets", tickets);
        body.put("total", total != null ? total : tickets.size());
        body.put("page", page == null ? 1 : page);
        body.put("pageSize", pageSize);
        return Response.ok(body).build();
    }

    /**
     * Feature 21/23: full ticket export as CSV, honouring exactly the same
     * filters as {@link #list} so "export" always means "what I am looking
     * at". Restricted by the `ticket.export` permission (admin/lead), which
     * has existed in {@link RbacPolicy} since Feature 11 but had no endpoint
     * behind it until now.
     *
     * Feature 23 widened what a row contains. The original export was the
     * QUEUE, column for column — so the export of a complaint-handling system
     * contained no complaint: not the citizen's name, not what they asked for,
     * not a word either side said, not who did what to the ticket. Everything
     * the ticket-detail page shows is now exported too, with the three
     * timelines (conversation, internal notes, audit trail) flattened into one
     * multi-line cell each. Deliberately still ONE ROW PER TICKET rather than
     * a row per message: the file stays a table that sorts, filters and pivots
     * on ticket attributes, which is what an export is for, and the
     * transcripts ride along in cells that Excel and Sheets both display
     * with their line breaks intact.
     *
     * `?detail=summary` returns the original flat shape. That matters because
     * the transcripts cost three extra db-writer calls per ticket, so the
     * full export is capped at {@value #DETAIL_MAX_ROWS} rows against the flat
     * export's {@value #EXPORT_MAX_ROWS} — a tenant-wide monthly pull wants
     * the flat one.
     *
     * Paged internally at db-writer's maximum (100/request) rather than asking
     * for everything at once: the queue query LEFT JOINs the identity table,
     * so an unbounded page would be the slowest query in the system, and this
     * keeps memory flat regardless of tenant size. An export that silently
     * stopped short would be worse than one that says so, so the cap is
     * reported in the response headers rather than being invisible.
     */
    @GET
    @Path("/export.csv")
    @Produces("text/csv")
    public Response exportCsv(@QueryParam("assignedTo") String assignedTo,
                              @QueryParam("status") String status,
                              @QueryParam("channel") String channel,
                              @QueryParam("category") String category,
                              @QueryParam("identityStatus") String identityStatus,
                              @QueryParam("sortBy") String sortBy,
                              @QueryParam("sortDir") String sortDir,
                              @QueryParam("detail") String detail) {
        if (!user.can("ticket.export")) {
            return forbidden("INSUFFICIENT_ROLE", "Your role cannot export tickets");
        }
        String resolvedAssignee = "me".equals(assignedTo) ? user.agentId() : assignedTo;
        if ("none".equals(assignedTo)) {
            resolvedAssignee = null;
        }
        // Full detail is the DEFAULT: the dashboard button sends no `detail`
        // param, and "export this ticket queue" almost always means "give me
        // the tickets", not "give me the columns I was already looking at".
        boolean full = !"summary".equalsIgnoreCase(detail);
        int maxRows = full ? DETAIL_MAX_ROWS : EXPORT_MAX_ROWS;
        List<String> columns = full ? fullColumns() : EXPORT_COLUMNS;

        Map<String, String> agentNames = agentDirectory();
        StringBuilder csv = new StringBuilder();
        csv.append(String.join(",", columns)).append("\r\n");

        int page = 1;
        int rows = 0;
        boolean truncated = false;
        while (rows < maxRows) {
            StringBuilder q = new StringBuilder("tenantId=").append(enc(user.tenantId()));
            append(q, "assignedTo", "none".equals(assignedTo) ? null : resolvedAssignee);
            append(q, "status", status);
            append(q, "channel", channel);
            append(q, "category", category);
            append(q, "identityStatus", identityStatus);
            append(q, "sortBy", sortBy == null ? "createdAt" : sortBy);
            append(q, "sortDir", sortDir == null ? "desc" : sortDir);
            append(q, "page", String.valueOf(page));
            append(q, "pageSize", String.valueOf(EXPORT_PAGE_SIZE));

            DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets?" + q, null);
            if (result.status() >= 400) {
                return Response.status(result.status()).entity(result.body()).build();
            }
            Object rawData = result.body() == null ? null : result.body().get("data");
            if (!(rawData instanceof List<?> list) || list.isEmpty()) {
                break;
            }
            for (Object o : list) {
                if (!(o instanceof Map<?, ?> mm)) {
                    continue;
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> t = (Map<String, Object>) mm;
                if (rows >= maxRows) {
                    truncated = true;
                    break;
                }
                if (full) {
                    t.putAll(ticketTimelines(str(t, "id"), agentNames));
                }
                csv.append(csvRow(t, agentNames, columns)).append("\r\n");
                rows++;
            }
            if (list.size() < EXPORT_PAGE_SIZE) {
                break;
            }
            page++;
        }

        String filename = "uniserve-tickets-" + java.time.LocalDate.now() + ".csv";
        Response.ResponseBuilder response = Response.ok(csv.toString())
                .header("Content-Disposition", "attachment; filename=\"" + filename + "\"")
                .header("X-Export-Row-Count", rows)
                // Which shape came back, so the dashboard can say "full detail"
                // vs "summary" instead of the user having to count columns.
                .header("X-Export-Detail", full ? "full" : "summary");
        if (truncated) {
            response.header("X-Export-Truncated", "true");
            response.header("X-Export-Row-Cap", maxRows);
        }
        return response.build();
    }

    private static final int EXPORT_PAGE_SIZE = 100;   // db-writer's own maximum
    private static final int EXPORT_MAX_ROWS = 50_000;
    /**
     * Full-detail rows each cost three extra db-writer calls (messages, notes,
     * events), so they are capped two orders of magnitude below the flat
     * export rather than sharing its limit. Anyone who needs more rows than
     * this wants `?detail=summary`, and the response headers say so.
     */
    private static final int DETAIL_MAX_ROWS = 2_000;

    /** Longest transcript kept in one cell. Excel's own hard limit is 32,767
     * characters per cell and it silently drops the overflow, so a long thread
     * is cut HERE, visibly, with a marker naming what was left out. */
    private static final int MAX_TRANSCRIPT_CHARS = 30_000;

    /** Package-private: {@code TicketExportAndCancelTest} asserts that the full
     * export is a superset of this, in this order. */
    static final List<String> EXPORT_COLUMNS = List.of(
            "ticket_number", "status", "identity_status", "chief_complaint", "category", "subcategory",
            "priority_label", "priority_score", "sentiment_score", "channel_origin",
            "citizen_name", "citizen_email", "citizen_phone", "service_id",
            "assigned_to_name", "is_duplicate", "parent_ticket_id", "resolution",
            "sla_due_at", "created_at", "updated_at", "resolved_at", "closed_at",
            "reopened_count", "thread_id", "id");

    /**
     * Appended for a full-detail export: the remaining ticket-detail fields
     * plus the three timelines. Order puts the transcripts LAST because they
     * are the wide cells — a spreadsheet opened on this file shows every
     * scalar column before it needs horizontal scrolling.
     */
    private static final List<String> DETAIL_COLUMNS = List.of(
            "identity_id", "origin_message_id", "reopened_by",
            "conversation", "internal_notes", "audit_trail");

    /** Package-private so {@code TicketExportAndCancelTest} can assert the
     * column contract without standing up a container. */
    static List<String> fullColumns() {
        List<String> cols = new ArrayList<>(EXPORT_COLUMNS);
        cols.addAll(DETAIL_COLUMNS);
        return cols;
    }

    static String csvRow(Map<String, Object> t, Map<String, String> agentNames, List<String> columns) {
        String assignedAgentId = str(t, "assigned_to");
        StringBuilder row = new StringBuilder();
        for (String column : columns) {
            if (row.length() > 0) {
                row.append(',');
            }
            Object value = "assigned_to_name".equals(column)
                    ? (assignedAgentId == null ? null : agentNames.get(assignedAgentId))
                    : t.get(column);
            row.append(csvCell(value));
        }
        return row.toString();
    }

    /**
     * The three per-ticket timelines the ticket-detail page shows, each
     * flattened to one newline-separated transcript for a single CSV cell.
     *
     * Best-effort per timeline (see {@link #timeline}): an export of 2,000
     * tickets must not fail outright because one ticket's notes fetch errored,
     * and a cell that SAYS it could not be read beats a blank one that is
     * indistinguishable from "this ticket has no notes".
     */
    private Map<String, Object> ticketTimelines(String ticketId, Map<String, String> agentNames) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("conversation", timeline(ticketId, "conversation", () -> conversationTranscript(ticketId)));
        out.put("internal_notes", timeline(ticketId, "notes", () -> notesTranscript(ticketId, agentNames)));
        out.put("audit_trail", timeline(ticketId, "audit trail", () -> auditTranscript(ticketId, agentNames)));
        return out;
    }

    /**
     * Isolate one timeline's failure to its own cell. `DbWriterClient.ticketNotes`
     * (and any transport fault behind the other two) throws a
     * {@code DbWriterException} on a 4xx/5xx, so without this a single
     * unreadable ticket would abort an entire 2,000-row export with a 500 —
     * losing 1,999 good rows over one bad one.
     */
    String timeline(String ticketId, String what, java.util.function.Supplier<String> read) {
        try {
            return read.get();
        } catch (RuntimeException e) {
            LOG.warnf("export: could not read %s for ticket %s: %s", what, ticketId, e.getMessage());
            return "[unavailable: this ticket's " + what + " could not be read at export time]";
        }
    }

    /** "[2026-08-04 09:12] Received · citizen: No power since morning" per line. */
    private String conversationTranscript(String ticketId) {
        StringBuilder out = new StringBuilder();
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets/" + ticketId + "/messages", null);
        if (result.status() >= 400 || result.body() == null) {
            // `db.call` is the non-throwing pass-through, so this is raised for
            // {@link #timeline} to turn into the same "unavailable" cell a
            // thrown failure produces — one wording, one place.
            throw new IllegalStateException("messages returned " + result.status());
        }
        if (result.body().get("data") instanceof List<?> list) {
            for (Object o : list) {
                if (!(o instanceof Map<?, ?> m)) {
                    continue;
                }
                String direction = "outbound".equals(String.valueOf(m.get("direction"))) ? "Sent" : "Received";
                // author_type is the raw enum (user/ai/agent/system); "citizen"
                // reads correctly in an export that a non-operator may open.
                Object authorType = m.get("author_type");
                String author = authorType == null ? "citizen" : String.valueOf(authorType);
                if ("user".equals(author)) {
                    author = "citizen";
                }
                appendEntry(out, m.get("created_at"), direction + " · " + author, m.get("content"));
            }
        }
        return truncateTranscript(out.toString(), "messages");
    }

    /**
     * Internal notes, including the mandatory transition notes — the written
     * justification for every resolve/close/reopen/cancel, and the single most
     * likely reason anyone exports a ticket in the first place.
     */
    private String notesTranscript(String ticketId, Map<String, String> agentNames) {
        StringBuilder out = new StringBuilder();
        for (Map<String, Object> n : db.ticketNotes(ticketId)) {
            String agentId = str(n, "agent_id");
            // A null agent is the system writing its own note (e.g. the
            // auto-close job), not an unknown agent.
            String author = agentId == null ? "System" : agentNames.getOrDefault(agentId, agentId);
            String transitionFrom = str(n, "transition_from");
            String transitionTo = str(n, "transition_to");
            if (transitionTo != null) {
                author += " (" + (transitionFrom == null ? "" : transitionFrom + "→") + transitionTo + ")";
            }
            appendEntry(out, n.get("created_at"), author, n.get("content"));
        }
        return truncateTranscript(out.toString(), "notes");
    }

    /** "[ts] status.resolved — Admin User {"...meta..."}" per line. */
    private String auditTranscript(String ticketId, Map<String, String> agentNames) {
        StringBuilder out = new StringBuilder();
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets/" + ticketId + "/events", null);
        if (result.status() >= 400 || result.body() == null) {
            throw new IllegalStateException("events returned " + result.status());   // see conversationTranscript
        }
        if (result.body().get("data") instanceof List<?> list) {
            for (Object o : list) {
                if (!(o instanceof Map<?, ?> e)) {
                    continue;
                }
                String actorId = e.get("actor_id") == null ? null : String.valueOf(e.get("actor_id"));
                Object actorType = e.get("actor_type");
                String actor = actorId == null
                        ? (actorType == null ? "system" : String.valueOf(actorType))
                        : agentNames.getOrDefault(actorId, actorId);
                Object meta = e.get("meta_json");
                appendEntry(out, e.get("created_at"), String.valueOf(e.get("event_type")),
                        actor + (meta == null ? "" : " " + meta));
            }
        }
        return truncateTranscript(out.toString(), "events");
    }

    /**
     * One transcript line: {@code [timestamp] label: body}. Newlines inside the
     * body are folded to spaces so each entry stays one line — the cell's own
     * line breaks then mean "next entry", which is what makes a 40-message
     * thread readable in a spreadsheet cell instead of a wall of text.
     */
    static void appendEntry(StringBuilder out, Object timestamp, String label, Object body) {
        String text = body == null ? "" : String.valueOf(body).replaceAll("\\s*\\R\\s*", " ").trim();
        if (out.length() > 0) {
            out.append('\n');
        }
        out.append('[').append(timestamp == null ? "" : timestamp).append("] ")
                .append(label).append(": ").append(text);
    }

    static String truncateTranscript(String transcript, String what) {
        if (transcript.length() <= MAX_TRANSCRIPT_CHARS) {
            return transcript;
        }
        // Cut on an entry boundary so the last line in the cell is a whole
        // entry rather than half of one.
        int cut = transcript.lastIndexOf('\n', MAX_TRANSCRIPT_CHARS);
        return transcript.substring(0, cut > 0 ? cut : MAX_TRANSCRIPT_CHARS)
                + "\n[… truncated: this ticket has more " + what + " than fit one cell]";
    }

    /**
     * RFC 4180 escaping. The leading-character guard is not cosmetic: a
     * citizen-supplied field starting with = + - or @ is executed as a formula
     * when the file is opened in Excel or Sheets (CSV injection), so it is
     * prefixed with a single quote — the standard neutralisation, and these
     * cells hold exactly the free text a citizen controls (names, resolutions).
     */
    static String csvCell(Object value) {
        if (value == null) {
            return "";
        }
        String s = String.valueOf(value);
        if (!s.isEmpty() && "=+-@\t\r".indexOf(s.charAt(0)) >= 0) {
            s = "'" + s;
        }
        if (s.indexOf('"') >= 0 || s.indexOf(',') >= 0 || s.indexOf('\n') >= 0 || s.indexOf('\r') >= 0) {
            return '"' + s.replace("\"", "\"\"") + '"';
        }
        return s;
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
        // Who performed the (re)assignment — recorded in the ticket's audit trail.
        patch.put("actorAgentId", user.agentId());
        DbWriterClient.ApiResult result = db.call("PATCH", "/api/v1/db/tickets/" + id, patch);
        return Response.status(result.status()).entity(result.body()).build();
    }

    /**
     * Audit trail for the ticket-detail page: creation, assignments, status
     * transitions — each with actor and timestamp. Actor/assignee agent ids are
     * resolved to display names here so the UI doesn't need the agents list.
     */
    @GET
    @Path("/{id}/events")
    public Response events(@PathParam("id") String id) {
        DbWriterClient.ApiResult result = db.call("GET", "/api/v1/db/tickets/" + id + "/events", null);
        if (result.status() >= 400) {
            return Response.status(result.status()).entity(result.body()).build();
        }
        Map<String, String> agentNames = agentDirectory();
        List<Map<String, Object>> events = new ArrayList<>();
        Object data = result.body() == null ? null : result.body().get("data");
        if (data instanceof List<?> list) {
            for (Object o : list) {
                if (!(o instanceof Map<?, ?> raw)) {
                    continue;
                }
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("eventType", raw.get("event_type"));
                e.put("actorType", raw.get("actor_type"));
                String actorId = raw.get("actor_id") == null ? null : String.valueOf(raw.get("actor_id"));
                e.put("actorName", actorId == null ? null : agentNames.getOrDefault(actorId, actorId));
                e.put("createdAt", raw.get("created_at"));
                // meta_json is tiny ({"assignedTo": "<agent id>"}); resolve the name.
                Object meta = raw.get("meta_json");
                if (meta != null) {
                    String metaStr = String.valueOf(meta);
                    int idx = metaStr.indexOf("\"assignedTo\":\"");
                    if (idx >= 0) {
                        String assignee = metaStr.substring(idx + 14, metaStr.indexOf('"', idx + 14));
                        e.put("assignedToName", agentNames.getOrDefault(assignee, assignee));
                    }
                    // Feature 22 duplicate events carry the ticket they point
                    // at. Parsed properly rather than by string index — this
                    // one drives a UI action, so a mangled value would send an
                    // agent to the wrong ticket.
                    e.putAll(duplicateMeta(metaStr));
                }
                events.add(e);
            }
        }
        return Response.ok(Map.of("events", events)).build();
    }

    /** Pull the duplicate-reference fields out of a ticket_event's meta_json. */
    private Map<String, Object> duplicateMeta(String metaJson) {
        Map<String, Object> out = new LinkedHashMap<>();
        try {
            Map<String, Object> parsed = new com.fasterxml.jackson.databind.ObjectMapper()
                    .readValue(metaJson, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
                    });
            for (String key : List.of("duplicateOfId", "duplicateOfNumber",
                    "mergedFromId", "mergedFromNumber", "reason")) {
                if (parsed.get(key) != null) {
                    out.put(key, parsed.get(key));
                }
            }
        } catch (Exception e) {
            // A malformed meta_json must not break the audit trail render.
            LOG.debugf("unparseable ticket_event meta_json: %s", metaJson);
        }
        return out;
    }

    /**
     * Feature 22: an agent's verdict on a suspected duplicate. Routing flags
     * the suspicion and the AI asks the citizen — but citizens often never
     * answer, and the flag would otherwise sit on the ticket forever with no
     * way to clear it. This is the same decision `resolve_duplicate` makes in
     * the conversation, taken by an agent instead, and it deliberately reuses
     * the identical treatment (`isDuplicate`/`parentTicketId`/closed) so there
     * is one meaning of "duplicate" in the system rather than two.
     */
    @POST
    @Path("/{id}/duplicate")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response resolveDuplicate(@PathParam("id") String id, Map<String, Object> input) {
        if (!user.can("ticket.edit")) {
            return forbidden("INSUFFICIENT_ROLE", "Your role cannot resolve duplicates");
        }
        Object flag = input == null ? null : input.get("isDuplicate");
        if (!(flag instanceof Boolean isDuplicate)) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "IS_DUPLICATE_REQUIRED", "message", "isDuplicate (true/false) is required"))).build();
        }
        String parentId = str(input, "duplicateOfId");
        if (Boolean.TRUE.equals(isDuplicate) && (parentId == null || parentId.isBlank())) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "DUPLICATE_OF_REQUIRED", "message", "duplicateOfId is required to confirm"))).build();
        }
        if (id.equals(parentId)) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "SAME_TICKET", "message", "A ticket cannot be a duplicate of itself"))).build();
        }

        Map<String, Object> meta = new LinkedHashMap<>();
        if (parentId != null) {
            meta.put("duplicateOfId", parentId);
        }
        if (!isDuplicate) {
            db.call("POST", "/api/v1/db/tickets/" + id + "/events", Map.of(
                    "eventType", "ticket.duplicate_dismissed", "actorType", "agent",
                    "actorId", user.agentId(), "meta", meta));
            return Response.ok(Map.of("isDuplicate", false)).build();
        }

        DbWriterClient.ApiResult patched = db.call("PATCH", "/api/v1/db/tickets/" + id, Map.of(
                "isDuplicate", 1, "parentTicketId", parentId, "status", "closed"));
        if (patched.status() >= 400) {
            return Response.status(patched.status()).entity(patched.body()).build();
        }
        db.call("POST", "/api/v1/db/tickets/" + id + "/events", Map.of(
                "eventType", "ticket.duplicate_confirmed", "actorType", "agent",
                "actorId", user.agentId(), "meta", meta));
        db.call("POST", "/api/v1/db/tickets/" + parentId + "/events", Map.of(
                "eventType", "ticket.duplicate_merged", "actorType", "agent",
                "actorId", user.agentId(), "meta", Map.of("mergedFromId", id)));
        return Response.ok(Map.of("isDuplicate", true, "parentTicketId", parentId)).build();
    }

    /**
     * Record the provider id of a message we just sent (Feature 24). Swallows
     * its own failure: the citizen HAS the message, and the only thing lost is
     * the ability to route their reply by id — every other rung still applies.
     */
    private void stampChannelMessageId(String ticketId, String messageRowId, String channelMessageId) {
        if (messageRowId == null) {
            return;
        }
        try {
            DbWriterClient.ApiResult patched = db.call("PATCH",
                    "/api/v1/db/tickets/" + ticketId + "/messages/" + messageRowId + "/channel-id",
                    Map.of("channelMessageId", channelMessageId));
            if (patched.status() >= 400) {
                LOG.warnf("could not record channel message id for ticket %s: %s", ticketId, patched.body());
            }
        } catch (Exception e) {
            LOG.warnf("could not record channel message id for ticket %s: %s", ticketId, e.getMessage());
        }
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
        // Feature 23: what the citizen actually wants, in one line, derived by
        // ai-core from their own messages (see ai-core's
        // app/tickets/chief_complaint.py). Null on a ticket that predates the
        // field or has not received an inbound message yet.
        body.put("chiefComplaint", t.get("chief_complaint"));
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
        // Feature 21: the dashboard offers Cancel only when the signed-in role
        // may actually perform it, decided HERE rather than from a role string
        // in the browser — same reasoning as canAssign, and the transition
        // endpoint re-checks it regardless.
        body.put("canCancel", user.can("ticket.status.to_cancelled"));
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
     * {@code ticket_messages} entry, and — for email- or WhatsApp-origin
     * tickets — actually sends it via {@link EmailAdapter#sendReply} or
     * {@link WhatsAppAdapter#sendReply}. Other (Phase 2) channels record the
     * message but have no outbound send wired.
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

        boolean sent = false;
        String sendError = null;
        String channelMessageId = null;
        if (("email".equals(channel) || "whatsapp".equals(channel)) && identityId != null) {
            DbWriterClient.ApiResult identity = db.call("GET", "/api/v1/db/identities/" + identityId, null);
            if ("email".equals(channel)) {
                String toAddress = identity.status() < 400 ? str(identity.body(), "email") : null;
                if (toAddress != null && !toAddress.isBlank()) {
                    try {
                        com.uniserve.adapters.SendResult result = emailAdapter.sendReply(
                                toAddress, "Update on your complaint " + ticketNumber, content, originMessageId);
                        sent = result.sent();
                        channelMessageId = result.channelMessageId();
                    } catch (Exception e) {
                        sendError = e.getMessage();
                        LOG.errorf(e, "Failed to send reply email for ticket %s", id);
                    }
                } else {
                    sendError = "No email address on file for this ticket's identity";
                }
            } else {
                String toPhone = identity.status() < 400 ? str(identity.body(), "phone") : null;
                if (toPhone != null && !toPhone.isBlank()) {
                    try {
                        com.uniserve.adapters.SendResult result =
                                whatsAppAdapter.sendReply(toPhone, content, originMessageId);
                        sent = result.sent();
                        channelMessageId = result.channelMessageId();
                    } catch (Exception e) {
                        sendError = e.getMessage();
                        LOG.errorf(e, "Failed to send WhatsApp reply for ticket %s", id);
                    }
                } else {
                    sendError = "No phone number on file for this ticket's identity";
                }
            }
        }

        // Feature 24: stamp the sent message with the provider's id, so when the
        // citizen replies to THIS message ("Is this resolved?" -> "Yes it is")
        // routing resolves it straight back to this ticket instead of guessing.
        // Best-effort and deliberately after the send: the agent's reply has
        // already reached the citizen, and losing a routing shortcut must never
        // turn a delivered message into a failed one.
        if (channelMessageId != null) {
            stampChannelMessageId(id, str(recorded.body(), "id"), channelMessageId);
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("recorded", true);
        response.put("channel", channel);
        response.put("sent", sent);
        if (sendError != null) {
            response.put("sendError", sendError);
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
            notifier.sendStatusUpdate(ticket, toStatus, noteContent);
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

    static String transitionAction(String toStatus) {
        return switch (toStatus == null ? "" : toStatus) {
            case "assigned" -> "ticket.status.open_to_assigned";
            case "in_progress" -> "ticket.status.assigned_to_inprogress";
            // Agent asked the citizen a question — any role may park the ticket.
            case "pending_customer" -> "ticket.status.to_pending_customer";
            case "resolved" -> "ticket.status.inprogress_to_resolved";
            case "closed" -> "ticket.status.resolved_to_closed";
            case "reopened" -> "ticket.status.closed_to_reopened";
            // Feature 21: admin-only, from any non-terminal status.
            case "cancelled" -> "ticket.status.to_cancelled";
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
