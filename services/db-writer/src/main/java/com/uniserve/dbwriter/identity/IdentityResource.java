package com.uniserve.dbwriter.identity;

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
import java.util.Optional;

/**
 * Identity-profile data API (Feature 04): {@code /api/v1/db/identities}.
 * Lookup by email/phone returns {@code {"data": [...]}} (empty when not found).
 */
@Path("/api/v1/db/identities")
@Produces(MediaType.APPLICATION_JSON)
public class IdentityResource {

    @Inject
    IdentityService identities;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(identities.create(body)).build();
    }

    @GET
    @Path("/{id}")
    public Response getById(@PathParam("id") String id) {
        return identities.getById(id)
                .<Response>map(p -> Response.ok(p).build())
                .orElseGet(() -> Response.status(404)
                        .entity(Map.of("error", Map.of("code", "NOT_FOUND", "message", "identity not found: " + id)))
                        .build());
    }

    @GET
    public Map<String, Object> find(@QueryParam("tenantId") String tenantId,
                                    @QueryParam("email") String email,
                                    @QueryParam("phone") String phone,
                                    @QueryParam("anonRefId") String anonRefId) {
        // anon refs are globally unique — no tenant required.
        if (anonRefId != null && !anonRefId.isBlank()) {
            return Map.of("data", identities.findByAnonRef(anonRefId).map(List::of).orElseGet(List::of));
        }
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        Optional<Map<String, Object>> match;
        if (email != null && !email.isBlank()) {
            match = identities.findByEmail(tenantId, email);
        } else if (phone != null && !phone.isBlank()) {
            match = identities.findByPhone(tenantId, phone);
        } else {
            return Map.of("data", identities.all(tenantId));
        }
        return Map.of("data", match.map(List::of).orElseGet(List::of));
    }

    @PATCH
    @Path("/{id}/merge")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> merge(@PathParam("id") String id, Map<String, Object> body) {
        return identities.merge(id, body);
    }

    /** Enrich with a newly-learned name/email/phone (Feature 03/06) — never overwrites a set field. */
    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Map<String, Object> update(@PathParam("id") String id, Map<String, Object> body) {
        return identities.update(id, body);
    }

    @GET
    @Path("/anon-check")
    public Map<String, Object> anonCheck(@QueryParam("tenantId") String tenantId,
                                         @QueryParam("anonRefId") String anonRefId) {
        if (tenantId == null || anonRefId == null) {
            throw new ApiException(400, "PARAMS_REQUIRED", "tenantId and anonRefId are required");
        }
        return Map.of("exists", identities.anonRefExists(tenantId, anonRefId));
    }

    @POST
    @Path("/pending")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response enqueuePending(Map<String, Object> body) {
        return Response.status(Response.Status.CREATED).entity(identities.enqueuePending(body)).build();
    }

    @GET
    @Path("/pending/timed-out")
    public Map<String, Object> timedOut(@QueryParam("tenantId") String tenantId) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        return Map.of("data", identities.timedOutPending(tenantId));
    }
}
