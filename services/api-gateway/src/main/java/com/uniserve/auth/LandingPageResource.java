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
 * Landing page content (Feature 25) — Admin only. Everything a citizen reads on
 * the public {@code /} page: headings, body copy, the logo, the palette, the
 * About/How-it-works/Contact sections, any extra sections, and the footer.
 *
 * <p>Stored as the {@code landingPage} key inside the tenant's existing
 * {@code config_json}, read-merge-write so the other keys (categories, SLA,
 * intakeFields, priorityRubric, generalSettings) survive a save — the same
 * approach as {@link GeneralSettingsResource}, and deliberately NOT
 * {@link TenantConfigResource}'s whole-object replace.
 *
 * <p>Defaults and validation live in {@link LandingPageContent} because
 * {@link PublicLandingPageResource} serves the same content unauthenticated;
 * one owner for both keeps the admin preview and the live page in agreement.
 */
@Path("/api/v1/tenant/landing-page")
@Produces(MediaType.APPLICATION_JSON)
public class LandingPageResource {

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
                "content", LandingPageContent.resolve(config),
                "defaults", LandingPageContent.defaults())).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Map<String, Object> cleaned;
        try {
            cleaned = LandingPageContent.normalise(body);
        } catch (LandingPageContent.InvalidContentException e) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "INVALID_LANDING_PAGE", "message", e.getMessage()))).build();
        }
        Map<String, Object> config = readConfig();
        config.put("landingPage", cleaned);
        try {
            db.updateTenantConfig(user.tenantId(), mapper.writeValueAsString(config));
        } catch (Exception e) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "INVALID_CONFIG", "message", String.valueOf(e.getMessage())))).build();
        }
        // Echo the RESOLVED view, not what was submitted: the panel's fields
        // then show the defaults that filled in whatever the admin left blank.
        return Response.ok(Map.of(
                "content", LandingPageContent.resolve(config),
                "defaults", LandingPageContent.defaults())).build();
    }

    private Map<String, Object> readConfig() {
        Map<String, Object> tenant = db.getTenant(user.tenantId());
        return LandingPageContent.parseConfig(mapper, tenant.get("config_json"));
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage the landing page"))).build();
    }
}
