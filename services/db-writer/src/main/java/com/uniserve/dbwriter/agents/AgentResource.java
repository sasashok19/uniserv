package com.uniserve.dbwriter.agents;

import com.uniserve.dbwriter.common.ApiException;
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

import java.util.List;
import java.util.Map;

/** Agent data API (Feature 04/11): {@code /api/v1/db/agents}. */
@Path("/api/v1/db/agents")
@Produces(MediaType.APPLICATION_JSON)
public class AgentResource {

    @Inject
    AgentService agents;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(agents.create(body)).build();
    }

    @GET
    public Map<String, Object> list(@QueryParam("tenantId") String tenantId,
                                    @QueryParam("email") String email) {
        if (email != null && !email.isBlank()) {
            return Map.of("data", agents.findByEmail(email).map(List::of).orElseGet(List::of));
        }
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId or email is required");
        }
        return Map.of("data", agents.list(tenantId));
    }

    @GET
    @Path("/{id}")
    public Map<String, Object> get(@PathParam("id") String id) {
        return agents.getById(id)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "agent not found: " + id));
    }

    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> patch(@PathParam("id") String id, Map<String, Object> body) {
        return agents.update(id, body);
    }
}
