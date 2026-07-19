package com.uniserve.auth;

import com.fasterxml.jackson.core.type.TypeReference;
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
 * Login-page news feed config — NO auth (the login page is public; the value
 * is just an RSS URL an admin chose in Administration → Settings,
 * {@code generalSettings.newsFeedUrl}). The dashboard's server-side
 * {@code /api/news} route consults this before its env/default fallbacks.
 */
@Path("/api/v1/public/news-config")
@Produces(MediaType.APPLICATION_JSON)
public class PublicNewsConfigResource {

    @Inject
    DbWriterClient db;

    @Inject
    ObjectMapper mapper;

    @ConfigProperty(name = "gateway.tenant-id")
    String tenantId;

    @GET
    public Response get() {
        String url = "";
        try {
            Map<String, Object> tenant = db.getTenant(tenantId);
            Object raw = tenant.get("config_json");
            if (raw != null) {
                Map<String, Object> config = mapper.readValue(String.valueOf(raw), new TypeReference<>() {
                });
                Object general = config.get("generalSettings");
                if (general instanceof Map<?, ?> g && g.get("newsFeedUrl") instanceof String s) {
                    url = s;
                }
            }
        } catch (Exception e) {
            // Public endpoint: degrade to "no override" rather than erroring.
        }
        return Response.ok(Map.of("newsFeedUrl", url)).build();
    }
}
