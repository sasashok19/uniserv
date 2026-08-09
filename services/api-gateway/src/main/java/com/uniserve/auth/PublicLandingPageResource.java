package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.Map;

/**
 * Landing page content for the public {@code /} page (Feature 25) — NO auth,
 * and deliberately not matched by {@link AuthFilter}'s {@code api/v1/tenant}
 * rule because of the {@code public/} segment, exactly like
 * {@link PublicNewsConfigResource} and {@link PublicAnnouncementsResource}.
 *
 * <p>Everything served here is copy an admin wrote for public display, so there
 * is nothing to leak — but note it is the admin-authored content only. It must
 * never grow to echo the rest of {@code config_json} (categories, SLA targets,
 * routing rules), which is not public.
 *
 * <p>Any failure — db-writer cold, config unparseable, tenant missing — returns
 * the built-in defaults with 200 rather than an error. The landing page is the
 * front door: it renders complete copy even when the backend is down.
 */
@Path("/api/v1/public/landing-page")
@Produces(MediaType.APPLICATION_JSON)
public class PublicLandingPageResource {

    @Inject
    DbWriterClient db;

    @Inject
    ObjectMapper mapper;

    /** Single-tenant Phase 1: the page shows the default tenant's content. */
    @ConfigProperty(name = "gateway.tenant-id")
    String tenantId;

    @GET
    public Response get() {
        Map<String, Object> content;
        try {
            Map<String, Object> tenant = db.getTenant(tenantId);
            content = LandingPageContent.resolve(
                    LandingPageContent.parseConfig(mapper, tenant.get("config_json")));
        } catch (Exception e) {
            content = LandingPageContent.defaults();
        }
        return Response.ok(Map.of("content", content)).build();
    }
}
