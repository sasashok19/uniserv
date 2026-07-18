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
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Per-channel configurable identity/intake fields (Feature 15/16) — Admin
 * only. Which fields are asked (Name, Mobile, Email, Service/Customer ID,
 * Area Pin Code) and whether each is mandatory (and separately,
 * mandatory-even-if-anonymous) is tenant-configurable per channel.
 *
 * <p>Stored as the {@code intakeFields} key inside the tenant's existing
 * {@code config_json} (alongside categories/SLA) — this resource only
 * reads/writes that one key, merging with whatever else is already there,
 * unlike {@link TenantConfigResource} which replaces the whole object.
 *
 * <p><b>Keep {@link #FIELD_CATALOG} in sync with</b>
 * {@code services/ai-core/app/conversation/intake_fields.py}'s
 * {@code FIELD_CATALOG} — this is the second of the two places that list
 * (key, label) since the extraction/validation logic itself only exists in
 * ai-core (Python); this copy is just for the UI's "available fields" list
 * and for validating a PUT body before it's saved.
 */
@Path("/api/v1/tenant/intake-fields")
@Produces(MediaType.APPLICATION_JSON)
public class IntakeFieldsResource {

    private static final List<Map<String, String>> FIELD_CATALOG = List.of(
            Map.of("key", "name", "label", "Name"),
            Map.of("key", "mobile", "label", "Mobile Number (10 digits)"),
            Map.of("key", "email", "label", "Email"),
            Map.of("key", "serviceId", "label", "Service/Customer ID"),
            Map.of("key", "pinCode", "label", "Area Pin Code (6 digits)"));

    private static final Set<String> VALID_KEYS = Set.of("name", "mobile", "email", "serviceId", "pinCode");
    private static final Set<String> VALID_CHANNELS = Set.of("email", "whatsapp");

    private static final Map<String, List<Map<String, Object>>> DEFAULTS = Map.of(
            "email", List.of(
                    field("name", true, false),
                    field("mobile", false, false),
                    field("serviceId", false, true),
                    field("pinCode", false, false)),
            "whatsapp", List.of(
                    field("name", true, false),
                    field("email", true, false),
                    field("serviceId", false, true)));

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
        Map<String, Object> intakeFields = configuredOrDefault(config);
        return Response.ok(Map.of("fields", intakeFields, "catalog", FIELD_CATALOG)).build();
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        String validationError = validate(body);
        if (validationError != null) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "INVALID_INTAKE_FIELDS", "message", validationError))).build();
        }
        Map<String, Object> config = readConfig();
        config.put("intakeFields", body);
        try {
            String json = mapper.writeValueAsString(config);
            db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(Map.of("fields", body, "catalog", FIELD_CATALOG)).build();
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
    private Map<String, Object> configuredOrDefault(Map<String, Object> config) {
        Object configured = config.get("intakeFields");
        Map<String, Object> result = new LinkedHashMap<>();
        Map<String, Object> configuredMap = configured instanceof Map ? (Map<String, Object>) configured : Map.of();
        for (String channel : VALID_CHANNELS) {
            result.put(channel, configuredMap.containsKey(channel) ? configuredMap.get(channel) : DEFAULTS.get(channel));
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private String validate(Map<String, Object> body) {
        if (body == null || body.isEmpty()) {
            return "at least one channel's field list is required";
        }
        for (Map.Entry<String, Object> entry : body.entrySet()) {
            String channel = entry.getKey();
            if (!VALID_CHANNELS.contains(channel)) {
                return "unknown channel '" + channel + "' — must be one of " + VALID_CHANNELS;
            }
            if (!(entry.getValue() instanceof List<?> fields)) {
                return "'" + channel + "' must be a list of field configs";
            }
            boolean hasMandatoryIdentityField = false;
            for (Object item : fields) {
                if (!(item instanceof Map)) {
                    return "each field config for '" + channel + "' must be an object";
                }
                Map<String, Object> field = (Map<String, Object>) item;
                Object key = field.get("key");
                if (!(key instanceof String) || !VALID_KEYS.contains(key)) {
                    return "unknown field key '" + key + "' — must be one of " + VALID_KEYS;
                }
                if (!(field.get("mandatory") instanceof Boolean) || !(field.get("mandatoryIfAnonymous") instanceof Boolean)) {
                    return "field '" + key + "' for '" + channel + "' must have boolean mandatory/mandatoryIfAnonymous";
                }
                if (("name".equals(key) || "email".equals(key) || "mobile".equals(key))
                        && (Boolean) field.get("mandatory")) {
                    hasMandatoryIdentityField = true;
                }
            }
            if (!hasMandatoryIdentityField) {
                return "'" + channel + "' must have at least one mandatory identity field (name, mobile, or email) "
                        + "so a ticket always has someone to resolve to";
            }
        }
        return null;
    }

    private static Map<String, Object> field(String key, boolean mandatory, boolean mandatoryIfAnonymous) {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("key", key);
        f.put("mandatory", mandatory);
        f.put("mandatoryIfAnonymous", mandatoryIfAnonymous);
        return f;
    }

    private Response forbidden() {
        return Response.status(403).entity(Map.of("error", Map.of(
                "code", "INSUFFICIENT_ROLE",
                "message", "Only admins can manage intake field configuration"))).build();
    }
}
