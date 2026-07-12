package com.uniserve.auth;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Public citizen-portal status lookup (Feature 12): {@code GET /api/v1/public/status/{ref}}.
 * No authentication. {@code ref} is an ANON-XXXX reference (or an email). Returns
 * only non-PII ticket status information.
 */
@Path("/api/v1/public/status")
@Produces(MediaType.APPLICATION_JSON)
public class PublicStatusResource {

    @Inject
    DbWriterClient db;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String defaultTenant;

    @GET
    @Path("/{ref}")
    public Response status(@PathParam("ref") String ref) {
        Optional<Map<String, Object>> profile = ref.contains("@")
                ? db.findIdentityByEmail(defaultTenant, ref)
                : db.findIdentityByAnonRef(ref);

        if (profile.isEmpty()) {
            return Response.status(404).entity(Map.of("error", Map.of(
                    "code", "NOT_FOUND", "message", "No record found for reference " + ref))).build();
        }

        Map<String, Object> p = profile.get();
        String tenantId = String.valueOf(p.get("tenant_id"));
        // tickets.identity_id is populated with the profile's masterId (see
        // ai-core's identity resolver, Feature 03), not its primary key.
        String identityId = String.valueOf(p.get("master_id"));

        List<Map<String, Object>> tickets = db.listTickets(
                "tenantId=" + enc(tenantId) + "&identityId=" + enc(identityId));

        List<Map<String, Object>> publicTickets = new ArrayList<>();
        for (Map<String, Object> t : tickets) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("ticketNumber", t.get("ticket_number"));
            view.put("status", t.get("status"));
            view.put("category", t.get("category"));
            view.put("lastUpdated", t.get("updated_at"));
            publicTickets.add(view);
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ref", ref);
        body.put("isAnonymous", intOf(p.get("is_anonymous")) == 1);
        body.put("tickets", publicTickets);
        return Response.ok(body).build();
    }

    private static int intOf(Object v) {
        return v instanceof Number n ? n.intValue() : 0;
    }

    private static String enc(String v) {
        return URLEncoder.encode(v, StandardCharsets.UTF_8);
    }
}
