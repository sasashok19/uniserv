package com.uniserve.dbwriter.announcements;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DELETE;
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

import com.uniserve.dbwriter.common.ApiException;

import java.util.Map;

/** Announcement data API (UI_REVAMP_v2 Feature C): {@code /api/v1/db/announcements}. */
@Path("/api/v1/db/announcements")
@Produces(MediaType.APPLICATION_JSON)
public class AnnouncementResource {

    @Inject
    AnnouncementService announcements;

    @GET
    public Map<String, Object> list(@QueryParam("tenantId") String tenantId,
                                    @QueryParam("activeOnly") @DefaultValue("false") boolean activeOnly) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        return Map.of("data", announcements.list(tenantId, activeOnly));
    }

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        return Response.status(201).entity(announcements.create(body)).build();
    }

    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> update(@PathParam("id") String id, Map<String, Object> body) {
        return announcements.update(id, body);
    }

    @DELETE
    @Path("/{id}")
    public Response delete(@PathParam("id") String id, @QueryParam("tenantId") String tenantId) {
        announcements.delete(id, tenantId);
        return Response.noContent().build();
    }
}
