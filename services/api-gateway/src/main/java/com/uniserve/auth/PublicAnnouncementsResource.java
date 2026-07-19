package com.uniserve.auth;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Public login-page announcement ticker (UI_REVAMP_v2 Feature C) — NO auth,
 * deliberately NOT in {@link AuthFilter#isProtected} (its path lives under
 * {@code /api/v1/public/} like the citizen status lookup). Exposes only
 * {@code id} + {@code title} of active, non-expired announcements for the
 * gateway's default tenant — never bodies or author details, since this is
 * readable by anyone who can reach the login page.
 */
@Path("/api/v1/public/announcements")
@Produces(MediaType.APPLICATION_JSON)
public class PublicAnnouncementsResource {

    @Inject
    DbWriterClient db;

    /** Single-tenant Phase 1: the ticker shows the default tenant's notices. */
    @ConfigProperty(name = "gateway.tenant-id")
    String tenantId;

    @GET
    public Response list() {
        DbWriterClient.ApiResult result = db.call("GET",
                "/api/v1/db/announcements?tenantId=" + URLEncoder.encode(tenantId, StandardCharsets.UTF_8)
                        + "&activeOnly=true", null);
        List<Map<String, Object>> out = new ArrayList<>();
        Object data = result.body() == null ? null : result.body().get("data");
        if (data instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> m) {
                    out.add(Map.of("id", String.valueOf(m.get("id")), "title", String.valueOf(m.get("title"))));
                }
            }
        }
        return Response.ok(Map.of("announcements", out)).build();
    }
}
