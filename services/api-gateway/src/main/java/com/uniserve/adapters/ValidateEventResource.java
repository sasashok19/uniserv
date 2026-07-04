package com.uniserve.adapters;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Adapter-contract validation endpoint (Feature 02f test stub):
 * {@code POST /api/v1/internal/validate-event}.
 *
 * <p>Returns {@code 200 {"valid": true}} for a well-formed
 * {@link ChannelMessageReceived}, or {@code 400 {"valid": false, "errors": [...]}}
 * when required fields are missing.
 *
 * <p>PHASE_1: unauthenticated — the {@code Authorization: Bearer} guard is
 * enforced once JWT verification is wired in 11_MULTI_TENANCY.
 */
@Path("/api/v1/internal/validate-event")
public class ValidateEventResource {

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response validate(ChannelMessageReceived event) {
        List<String> errors = EventValidator.validate(event);
        if (errors.isEmpty()) {
            return Response.ok(Map.of("valid", true)).build();
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("valid", false);
        body.put("errors", errors);
        return Response.status(Response.Status.BAD_REQUEST).entity(body).build();
    }
}
