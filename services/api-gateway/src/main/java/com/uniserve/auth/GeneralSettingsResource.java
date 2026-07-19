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
 * General tenant settings (Feature 4) — Admin only. Currently a single field,
 * {@code maxFollowupQuestions} (0-5), consumed by ai-core's conversation agent
 * to cap how many follow-up questions it asks per intake.
 *
 * <p>Stored as the {@code generalSettings} key inside the tenant's existing
 * {@code config_json} (alongside categories/SLA/intakeFields/priorityRubric) —
 * this resource only reads/writes that one key, merging with whatever else is
 * already there, unlike {@link TenantConfigResource} which replaces the whole
 * object. Mirrors {@link IntakeFieldsResource}'s read-merge-write approach.
 */
@Path("/api/v1/tenant/general-settings")
@Produces(MediaType.APPLICATION_JSON)
public class GeneralSettingsResource {

    private static final int DEFAULT_MAX_FOLLOWUP_QUESTIONS = 2;
    private static final int MIN_FOLLOWUP_QUESTIONS = 0;
    private static final int MAX_FOLLOWUP_QUESTIONS = 5;

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
        int effective = configuredMaxFollowup(config);
        return Response.ok(Map.of(
                "settings", Map.of("maxFollowupQuestions", effective),
                "defaults", Map.of("maxFollowupQuestions", DEFAULT_MAX_FOLLOWUP_QUESTIONS))).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Object raw = body == null ? null : body.get("maxFollowupQuestions");
        Integer value = asInt(raw);
        if (value == null || value < MIN_FOLLOWUP_QUESTIONS || value > MAX_FOLLOWUP_QUESTIONS) {
            return invalid("'maxFollowupQuestions' must be an integer between "
                    + MIN_FOLLOWUP_QUESTIONS + " and " + MAX_FOLLOWUP_QUESTIONS);
        }
        Map<String, Object> config = readConfig();
        Map<String, Object> settings = new LinkedHashMap<>();
        settings.put("maxFollowupQuestions", value);
        config.put("generalSettings", settings);
        try {
            String json = mapper.writeValueAsString(config);
            db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(Map.of(
                    "settings", Map.of("maxFollowupQuestions", value),
                    "defaults", Map.of("maxFollowupQuestions", DEFAULT_MAX_FOLLOWUP_QUESTIONS))).build();
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

    @SuppressWarnings("unchecked")
    private int configuredMaxFollowup(Map<String, Object> config) {
        Object general = config.get("generalSettings");
        if (general instanceof Map) {
            Integer v = asInt(((Map<String, Object>) general).get("maxFollowupQuestions"));
            if (v != null && v >= MIN_FOLLOWUP_QUESTIONS && v <= MAX_FOLLOWUP_QUESTIONS) {
                return v;
            }
        }
        return DEFAULT_MAX_FOLLOWUP_QUESTIONS;
    }

    /** Accept only true integers (reject booleans, decimals, and non-integral doubles). */
    private static Integer asInt(Object raw) {
        if (raw instanceof Integer i) {
            return i;
        }
        if (raw instanceof Long l && l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) {
            return (int) (long) l;
        }
        if (raw instanceof Number n && !(raw instanceof Double) && !(raw instanceof Float)) {
            return n.intValue();
        }
        if (raw instanceof Double d && d == Math.floor(d) && !d.isInfinite()) {
            return (int) (double) d;
        }
        return null;
    }

    private Response invalid(String message) {
        return Response.status(422).entity(Map.of("error", Map.of(
                "code", "INVALID_GENERAL_SETTINGS", "message", message))).build();
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage general settings"))).build();
    }
}
