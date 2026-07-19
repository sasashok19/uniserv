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

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

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

    // Tenant-defined custom fields (stored under `intakeFieldCatalog` in
    // config_json; ai-core's catalog_for_tenant() gives each a generic
    // label-anchored extractor + validator, so a field added here cascades to
    // the bot's intake form/validation with no further code).
    private static final Pattern CUSTOM_KEY = Pattern.compile("^[A-Za-z][A-Za-z0-9]{1,29}$");
    private static final Set<String> CUSTOM_VALIDATIONS = Set.of("text", "digits");
    private static final int MAX_CUSTOM_FIELDS = 10;

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
        return Response.ok(Map.of(
                "fields", intakeFields,
                "catalog", mergedCatalog(config),
                "customFields", customFields(config))).build();
    }

    /**
     * Manage the tenant's custom field catalog. Replaces the whole custom list
     * (built-ins are fixed); a custom field removed here is also stripped from
     * every channel's configured list so no dangling keys remain.
     */
    @PUT
    @Path("/catalog")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response updateCatalog(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Object raw = body == null ? null : body.get("customFields");
        if (!(raw instanceof List<?> list)) {
            return invalidCatalog("'customFields' must be a list");
        }
        if (list.size() > MAX_CUSTOM_FIELDS) {
            return invalidCatalog("at most " + MAX_CUSTOM_FIELDS + " custom fields are supported");
        }
        List<Map<String, Object>> customs = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Object item : list) {
            if (!(item instanceof Map)) {
                return invalidCatalog("each custom field must be an object");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> f = (Map<String, Object>) item;
            Object key = f.get("key");
            Object label = f.get("label");
            if (!(key instanceof String k) || !CUSTOM_KEY.matcher(k).matches()) {
                return invalidCatalog("invalid field key '" + key + "' (letters/digits, 2-30 chars, letter first)");
            }
            if (VALID_KEYS.contains(k) || !seen.add(k)) {
                return invalidCatalog("field key '" + k + "' collides with a built-in or is duplicated");
            }
            if (!(label instanceof String l) || l.trim().length() < 2 || l.trim().length() > 40) {
                return invalidCatalog("field '" + k + "' needs a label of 2-40 characters");
            }
            Object validation = f.getOrDefault("validation", "text");
            if (!(validation instanceof String v) || !CUSTOM_VALIDATIONS.contains(v)) {
                return invalidCatalog("field '" + k + "' validation must be one of " + CUSTOM_VALIDATIONS);
            }
            Map<String, Object> clean = new LinkedHashMap<>();
            clean.put("key", k);
            clean.put("label", ((String) label).trim());
            clean.put("validation", validation);
            if ("digits".equals(validation) && f.get("digits") != null) {
                if (!(f.get("digits") instanceof Number n) || n.intValue() < 1 || n.intValue() > 20) {
                    return invalidCatalog("field '" + k + "' digits length must be 1-20");
                }
                clean.put("digits", n.intValue());
            }
            customs.add(clean);
        }

        Map<String, Object> config = readConfig();
        config.put("intakeFieldCatalog", customs);
        stripRemovedKeys(config, customs);
        try {
            String json = mapper.writeValueAsString(config);
            db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(Map.of(
                    "fields", configuredOrDefault(config),
                    "catalog", mergedCatalog(config),
                    "customFields", customs)).build();
        } catch (Exception e) {
            return Response.status(400).entity(Map.of("error", Map.of(
                    "code", "INVALID_CONFIG", "message", e.getMessage()))).build();
        }
    }

    @PUT
    @Consumes(MediaType.APPLICATION_JSON)
    public Response update(Map<String, Object> body) {
        if (!user.can("admin.tenant.config")) {
            return forbidden();
        }
        Map<String, Object> config = readConfig();
        String validationError = validate(body, allValidKeys(config));
        if (validationError != null) {
            return Response.status(422).entity(Map.of("error", Map.of(
                    "code", "INVALID_INTAKE_FIELDS", "message", validationError))).build();
        }
        config.put("intakeFields", body);
        try {
            String json = mapper.writeValueAsString(config);
            db.updateTenantConfig(user.tenantId(), json);
            return Response.ok(Map.of(
                    "fields", body,
                    "catalog", mergedCatalog(config),
                    "customFields", customFields(config))).build();
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

    /** Built-in keys plus the tenant's custom-catalog keys. */
    @SuppressWarnings("unchecked")
    private static Set<String> allValidKeys(Map<String, Object> config) {
        Set<String> keys = new HashSet<>(VALID_KEYS);
        for (Map<String, Object> f : customFields(config)) {
            Object key = f.get("key");
            if (key instanceof String k) {
                keys.add(k);
            }
        }
        return keys;
    }

    /** The tenant's stored custom field definitions (empty list when none). */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> customFields(Map<String, Object> config) {
        Object raw = config.get("intakeFieldCatalog");
        List<Map<String, Object>> out = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map) {
                    out.add((Map<String, Object>) o);
                }
            }
        }
        return out;
    }

    /** Built-in catalog (flagged builtin=true) + custom fields (builtin=false), for the UI. */
    private static List<Map<String, Object>> mergedCatalog(Map<String, Object> config) {
        List<Map<String, Object>> catalog = new ArrayList<>();
        for (Map<String, String> f : FIELD_CATALOG) {
            catalog.add(Map.of("key", f.get("key"), "label", f.get("label"), "builtin", true));
        }
        for (Map<String, Object> f : customFields(config)) {
            Map<String, Object> entry = new LinkedHashMap<>(f);
            entry.put("builtin", false);
            catalog.add(entry);
        }
        return catalog;
    }

    /** Remove channel-config references to custom keys that no longer exist. */
    @SuppressWarnings("unchecked")
    private static void stripRemovedKeys(Map<String, Object> config, List<Map<String, Object>> customs) {
        Set<String> valid = new HashSet<>(VALID_KEYS);
        for (Map<String, Object> f : customs) {
            valid.add(String.valueOf(f.get("key")));
        }
        Object intake = config.get("intakeFields");
        if (!(intake instanceof Map)) {
            return;
        }
        for (Map.Entry<String, Object> channel : ((Map<String, Object>) intake).entrySet()) {
            if (channel.getValue() instanceof List<?> fields) {
                List<Object> kept = new ArrayList<>();
                for (Object item : fields) {
                    if (item instanceof Map && valid.contains(String.valueOf(((Map<String, Object>) item).get("key")))) {
                        kept.add(item);
                    }
                }
                channel.setValue(kept);
            }
        }
    }

    private Response invalidCatalog(String message) {
        return Response.status(422).entity(Map.of("error", Map.of(
                "code", "INVALID_FIELD_CATALOG", "message", message))).build();
    }

    @SuppressWarnings("unchecked")
    private String validate(Map<String, Object> body, Set<String> validKeys) {
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
                if (!(key instanceof String) || !validKeys.contains(key)) {
                    return "unknown field key '" + key + "' — must be one of " + validKeys;
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
