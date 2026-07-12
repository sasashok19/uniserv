package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PATCH;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.List;
import java.util.Map;

/**
 * Ticket data API (Feature 04): {@code /api/v1/db/tickets}. All CRUD, queue
 * listing, status transitions, notes, messages, audit events, and the AI
 * resolution-summary endpoint.
 */
@Path("/api/v1/db/tickets")
@Produces(MediaType.APPLICATION_JSON)
public class TicketResource {

    @Inject
    TicketService tickets;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        Map<String, Object> created = tickets.create(body);
        return Response.status(Response.Status.CREATED)
                .entity(Map.of(
                        "id", created.get("id"),
                        "ticketNumber", created.get("ticket_number"),
                        "status", created.get("status")))
                .build();
    }

    @GET
    @Path("/{id}")
    public Response get(@PathParam("id") String id) {
        TicketService.CacheResult result = tickets.getCached(id);
        if (result.ticket() == null) {
            throw new ApiException(404, "NOT_FOUND", "ticket not found: " + id);
        }
        return Response.ok(result.ticket())
                .header("X-Cache", result.hit() ? "HIT" : "MISS")
                .build();
    }

    @GET
    public Map<String, Object> list(@QueryParam("tenantId") String tenantId,
                                    @QueryParam("status") String status,
                                    @QueryParam("assignedTo") String assignedTo,
                                    @QueryParam("channel") String channel,
                                    @QueryParam("category") String category,
                                    @QueryParam("identityId") String identityId,
                                    @QueryParam("identityStatus") String identityStatus,
                                    @QueryParam("threadId") String threadId,
                                    @QueryParam("includeArchived") @DefaultValue("false") boolean includeArchived,
                                    @QueryParam("page") @DefaultValue("1") int page,
                                    @QueryParam("pageSize") @DefaultValue("20") int pageSize) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        int size = Math.min(Math.max(pageSize, 1), 100);
        List<Map<String, Object>> data = tickets.list(tenantId, status, assignedTo, channel, category, identityId,
                identityStatus, threadId, includeArchived, page, size);
        return Map.of("data", data, "page", page, "pageSize", size, "total", data.size());
    }

    /** Archive (soft-delete) unconfirmed tickets older than N days (Feature 12 admin cleanup). */
    @POST
    @Path("/archive-stale")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> archiveStale(Map<String, Object> body) {
        Object tenantIdObj = body.get("tenantId");
        Object daysObj = body.get("olderThanDays");
        if (tenantIdObj == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        int olderThanDays = daysObj == null ? 60 : ((Number) daysObj).intValue();
        int archived = tickets.archiveStale(String.valueOf(tenantIdObj), olderThanDays);
        return Map.of("archived", archived);
    }

    /** Auto-close (status=closed) unconfirmed tickets older than N days (Feature 06 x 14), across all tenants. */
    @POST
    @Path("/auto-close-unconfirmed")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> autoCloseUnconfirmed(Map<String, Object> body) {
        Object daysObj = body == null ? null : body.get("olderThanDays");
        int olderThanDays = daysObj == null ? 14 : ((Number) daysObj).intValue();
        return Map.of("closed", tickets.autoCloseUnconfirmed(olderThanDays));
    }

    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> patch(@PathParam("id") String id, Map<String, Object> body) {
        return tickets.update(id, body);
    }

    @POST
    @Path("/{id}/transition")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> transition(@PathParam("id") String id, Map<String, Object> body) {
        return tickets.transition(id, body);
    }

    @POST
    @Path("/{id}/notes")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response addNote(@PathParam("id") String id, Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(tickets.addNote(id, body)).build();
    }

    @GET
    @Path("/{id}/notes")
    public Map<String, Object> notes(@PathParam("id") String id) {
        return Map.of("data", tickets.notes(id));
    }

    @GET
    @Path("/{id}/messages")
    public Map<String, Object> messages(@PathParam("id") String id) {
        return Map.of("data", tickets.messages(id));
    }

    @POST
    @Path("/{id}/messages")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response addMessage(@PathParam("id") String id, Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(tickets.addMessage(id, body)).build();
    }

    @GET
    @Path("/{id}/events")
    public Map<String, Object> events(@PathParam("id") String id) {
        return Map.of("data", tickets.events(id));
    }

    @POST
    @Path("/{id}/generate-resolution-summary")
    public Map<String, Object> resolutionSummary(@PathParam("id") String id) {
        return tickets.resolutionSummary(id);
    }
}
