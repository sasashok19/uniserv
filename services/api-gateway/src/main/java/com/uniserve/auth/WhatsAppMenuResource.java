package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.Map;

/**
 * WhatsApp conversation menu (Feature 26) — Admin only. The welcome message,
 * the 1/2/3 options and every other string the citizen reads on WhatsApp,
 * including the company name the welcome greets them with.
 *
 * <p>Stored as the {@code whatsappMenu} key inside the tenant's existing
 * {@code config_json}, read-merge-write so the other keys survive a save — the
 * same approach as {@link LandingPageResource} and {@link GeneralSettingsResource},
 * and deliberately NOT {@link TenantConfigResource}'s whole-object replace.
 *
 * <p>There is no public counterpart to this resource. Unlike the landing page,
 * nothing renders this content to an anonymous browser: ai-core reads the stored
 * blob directly from db-writer over the internal network, so the copy never
 * needs an unauthenticated endpoint.
 */
@Path("/api/v1/tenant/whatsapp-menu")
@Produces(MediaType.APPLICATION_JSON)
public class WhatsAppMenuResource {

    @Inject
    CurrentUser user;

    @Inject
    DbWriterClient db;

    @Inject
    ObjectMapper mapper;

    @GET
    public Response get() {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Map<String, Object> config = readConfig();
        return Response.ok(Map.of(
                "content", WhatsAppMenuContent.resolve(config),
                "defaults", WhatsAppMenuContent.defaults())).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Map<String, Object> cleaned;
        try {
            cleaned = WhatsAppMenuContent.normalise(body);
        } catch (WhatsAppMenuContent.InvalidContentException e) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "INVALID_WHATSAPP_MENU", "message", e.getMessage()))).build();
        }
        Map<String, Object> config = readConfig();
        config.put("whatsappMenu", cleaned);
        try {
            db.updateTenantConfig(user.tenantId(), mapper.writeValueAsString(config));
        } catch (Exception e) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "INVALID_CONFIG", "message", String.valueOf(e.getMessage())))).build();
        }
        // Echo the RESOLVED view, not what was submitted: the panel's fields
        // then show the defaults that filled in whatever the admin left blank.
        return Response.ok(Map.of(
                "content", WhatsAppMenuContent.resolve(config),
                "defaults", WhatsAppMenuContent.defaults())).build();
    }

    private Map<String, Object> readConfig() {
        Map<String, Object> tenant = db.getTenant(user.tenantId());
        return LandingPageContent.parseConfig(mapper, tenant.get("config_json"));
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage the WhatsApp menu"))).build();
    }
}
