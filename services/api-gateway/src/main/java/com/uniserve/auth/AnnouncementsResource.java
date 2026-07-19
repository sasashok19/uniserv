package com.uniserve.auth;

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

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Tenant announcements (UI_REVAMP_v2 Feature C) — read for every authenticated
 * role (topbar bell/banner), manage for admins (Administration → Announcements).
 * The unauthenticated login-page ticker uses {@link PublicAnnouncementsResource}
 * instead, which exposes titles only.
 *
 * <p><b>Path registered in {@link AuthFilter#isProtected}</b> — without that,
 * {@link CurrentUser} is silently unpopulated (see AuthFilter's class doc).
 */
@Path("/api/v1/announcements")
@Produces(MediaType.APPLICATION_JSON)
public class AnnouncementsResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @GET
    public Response list(@QueryParam("activeOnly") @DefaultValue("false") boolean activeOnly) {
        if (!user.can("announcements.view")) {
            return forbidden("Not allowed to view announcements");
        }
        DbWriterClient.ApiResult result = db.call("GET",
                "/api/v1/db/announcements?tenantId=" + enc(user.tenantId()) + "&activeOnly=" + activeOnly, null);
        Object data = result.body() == null ? null : result.body().get("data");
        return Response.status(result.status())
                .entity(Map.of("announcements", data instanceof List<?> list ? list : List.of()))
                .build();
    }

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(Map<String, Object> input) {
        if (!user.can("announcements.manage")) {
            return forbidden("Only admins can manage announcements");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tenantId", user.tenantId());
        body.put("createdBy", user.agentId());
        if (input != null) {
            body.put("title", input.get("title"));
            body.put("body", input.get("body"));
            if (input.get("expiresAt") != null) {
                body.put("expiresAt", input.get("expiresAt"));
            }
        }
        DbWriterClient.ApiResult result = db.call("POST", "/api/v1/db/announcements", body);
        return Response.status(result.status()).entity(result.body()).build();
    }

    @PATCH
    @Path("/{id}")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(@PathParam("id") String id, Map<String, Object> input) {
        if (!user.can("announcements.manage")) {
            return forbidden("Only admins can manage announcements");
        }
        DbWriterClient.ApiResult result = db.call("PATCH", "/api/v1/db/announcements/" + id, input);
        return Response.status(result.status()).entity(result.body()).build();
    }

    @DELETE
    @Path("/{id}")
    public Response delete(@PathParam("id") String id) {
        if (!user.can("announcements.manage")) {
            return forbidden("Only admins can manage announcements");
        }
        DbWriterClient.ApiResult result = db.call("DELETE",
                "/api/v1/db/announcements/" + id + "?tenantId=" + enc(user.tenantId()), null);
        return Response.status(result.status()).entity(result.body()).build();
    }

    private static String enc(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private Response forbidden(String message) {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE", "message", message))).build();
    }
}
