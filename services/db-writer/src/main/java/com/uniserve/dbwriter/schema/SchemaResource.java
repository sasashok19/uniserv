package com.uniserve.dbwriter.schema;

import com.uniserve.dbwriter.db.Db;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Schema inspection endpoints (Feature 05 test stubs):
 * <ul>
 *   <li>{@code GET /api/v1/internal/schema/version} — latest Flyway version + count.</li>
 *   <li>{@code GET /api/v1/internal/schema/tables} — the created tables.</li>
 * </ul>
 *
 * <p>PHASE_1: unauthenticated (the doc's {@code Authorization: Bearer} guard arrives
 * with JWT in 11_MULTI_TENANCY).
 */
@Path("/api/v1/internal/schema")
public class SchemaResource {

    /** Canonical table order (from the schema spec) for a stable response. */
    private static final List<String> EXPECTED_ORDER = List.of(
            "tenants", "agents", "identity_profiles", "tickets",
            "ticket_messages", "ticket_notes", "ticket_events", "identity_pending_queue");

    @Inject
    Db db;

    @GET
    @Path("/version")
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> version() {
        Object version = db.scalar(
                "SELECT version FROM flyway_schema_history WHERE success = 1 ORDER BY installed_rank DESC LIMIT 1");
        Object applied = db.scalar(
                "SELECT COUNT(*) FROM flyway_schema_history WHERE success = 1");
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("version", version == null ? null : String.valueOf(version));
        body.put("appliedMigrations", applied == null ? 0 : ((Number) applied).intValue());
        return body;
    }

    @GET
    @Path("/tables")
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> tables() {
        List<Map<String, Object>> rows = db.query(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                        + "AND name NOT LIKE 'sqlite_%' AND name <> 'flyway_schema_history'");
        List<String> found = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            found.add(String.valueOf(row.get("name")));
        }
        // Present in the canonical order, then any extras.
        List<String> ordered = new ArrayList<>();
        for (String t : EXPECTED_ORDER) {
            if (found.remove(t)) {
                ordered.add(t);
            }
        }
        ordered.addAll(found);
        return Map.of("tables", ordered);
    }
}
