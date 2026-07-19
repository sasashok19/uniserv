package com.uniserve.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * AI priority rubric (Feature 3) — Admin only. A free-text rubric that ai-core
 * uses to score complaint priority via an LLM when set (and a key is available);
 * otherwise ai-core falls back to its deterministic engine.
 *
 * <p>Stored as the {@code priorityRubric} key inside the tenant's existing
 * {@code config_json} (alongside categories/SLA/intakeFields/generalSettings) —
 * this resource only reads/writes that one key, merging with whatever else is
 * already there, unlike {@link TenantConfigResource} which replaces the whole
 * object. Mirrors {@link IntakeFieldsResource}'s read-merge-write approach.
 *
 * <p>{@link #DEFAULT_RUBRIC} is the plain-English writeup of ai-core's CURRENT
 * deterministic engine, served on GET so the admin screen is pre-populated with
 * today's logic. Leaving the stored rubric as this default keeps today's
 * behavior.
 */
@Path("/api/v1/tenant/priority-rubric")
@Produces(MediaType.APPLICATION_JSON)
public class PriorityRubricResource {

    private static final int MAX_LENGTH = 8000;

    static final String DEFAULT_RUBRIC = """
            Assess complaint priority on a 0-10 scale, then bucket it: 8-10 = critical, 6-7.9 = high, 4-5.9 = medium, below 4 = low.

            Weigh these factors (this reflects the system's current default logic):
            - Sentiment / urgency of the citizen's language (weight ~25%): angrier or more distressed wording raises priority.
            - Time-sensitivity / SLA pressure (weight ~25%): the closer to a promised resolution time, the higher.
            - Repeat contact (weight ~20%): a citizen who has contacted us multiple times about this is higher.
            - Category severity (weight ~15%): power outage is most severe (~9/10); billing and technical are moderate (~6/10); service and product are ~5/10; anything uncategorised is ~4/10.
            - Channel (weight ~10%): WhatsApp is treated as slightly more urgent than email.
            - Vulnerability signals (weight ~5%): mentions of safety, medical need, elderly, or emergency raise priority.

            Return your answer as strict JSON: {"score": <number 0-10>, "label": "<critical|high|medium|low>"}.""";

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
        return Response.ok(Map.of("rubric", storedRubric(config), "default", DEFAULT_RUBRIC)).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Object raw = body == null ? null : body.get("rubric");
        if (raw != null && !(raw instanceof String)) {
            return invalid("'rubric' must be a string");
        }
        String rubric = raw == null ? "" : (String) raw;
        if (rubric.length() > MAX_LENGTH) {
            return invalid("'rubric' must be at most " + MAX_LENGTH + " characters");
        }
        Map<String, Object> config = readConfig();
        if (rubric.isEmpty()) {
            config.remove("priorityRubric");
        } else {
            config.put("priorityRubric", rubric);
        }
        try {
            String json = mapper.writeValueAsString(config);
            db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(Map.of("rubric", rubric, "default", DEFAULT_RUBRIC)).build();
        } catch (Exception e) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "INVALID_CONFIG", "message", e.getMessage()))).build();
        }
    }

    // ---- helpers -----------------------------------------------------

    @SuppressWarnings("unchecked")
    private Map<String, Object> readConfig() {
        Map<String, Object> tenant = db.getTenant(user.tenantId());
        Object raw = tenant.get("config_json");
        if (raw == null) {
            return new LinkedHashMap<>();
        }
        try {
            Map<String, Object> parsed = mapper.readValue(String.valueOf(raw), new TypeReference<>() {
            });
            return new LinkedHashMap<>(parsed);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    private String storedRubric(Map<String, Object> config) {
        Object stored = config.get("priorityRubric");
        return stored instanceof String ? (String) stored : "";
    }

    private Response invalid(String message) {
        return Response.status(422).entity(Map.of("error", Map.of(
                "code", "INVALID_PRIORITY_RUBRIC", "message", message))).build();
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage the priority rubric"))).build();
    }
}
