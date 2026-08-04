package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Unrouted citizen messages (Feature 24): {@code /api/v1/db/unrouted-messages}.
 *
 * Written by ai-core when routing declines every rung, read and resolved by
 * leads/admins through the gateway.
 */
@Path("/api/v1/db/unrouted-messages")
@Produces(MediaType.APPLICATION_JSON)
public class UnroutedMessageResource {

    @Inject
    UnroutedMessageService unrouted;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(unrouted.create(body)).build();
    }

    @GET
    public Map<String, Object> list(@QueryParam("tenantId") String tenantId,
                                    @QueryParam("status") String status,
                                    @QueryParam("page") @DefaultValue("1") int page,
                                    @QueryParam("pageSize") @DefaultValue("30") int pageSize) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("data", unrouted.list(tenantId, status, page, pageSize));
        out.put("total", unrouted.count(tenantId, status));
        return out;
    }

    /**
     * How many times this contact has already been asked to clarify since
     * {@code since} (Feature 24). ai-core calls this before deciding between
     * asking again and escalating, so "I don't have it" never loops.
     */
    @GET
    @Path("/ask-count")
    public Map<String, Object> askCount(@QueryParam("tenantId") String tenantId,
                                        @QueryParam("channelIdentityValue") String value,
                                        @QueryParam("since") String since) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        return Map.of("askCount", unrouted.recentAskCount(tenantId, value, since));
    }

    @POST
    @Path("/{id}/attach")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> attach(@PathParam("id") String id, Map<String, Object> body) {
        Object ticketId = body == null ? null : body.get("ticketId");
        if (ticketId == null || String.valueOf(ticketId).isBlank()) {
            throw new ApiException(422, "TICKET_REQUIRED", "ticketId is required");
        }
        Object agentId = body.get("agentId");
        return unrouted.attach(id, String.valueOf(ticketId),
                agentId == null ? null : String.valueOf(agentId));
    }

    @POST
    @Path("/{id}/discard")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> discard(@PathParam("id") String id, Map<String, Object> body) {
        Object agentId = body == null ? null : body.get("agentId");
        return unrouted.discard(id, agentId == null ? null : String.valueOf(agentId));
    }
}
