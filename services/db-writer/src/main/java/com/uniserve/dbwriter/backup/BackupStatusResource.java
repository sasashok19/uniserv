package com.uniserve.dbwriter.backup;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Backup status (Feature 16): {@code GET /api/v1/internal/backup/status}.
 *
 * <p>PHASE_1: the actual backups are performed by the {@code db-backup} sidecar in
 * Kubernetes (not present in local compose), so {@code lastBackup} is null here.
 * The endpoint reports the live SQLite file size and the configured destination.
 */
@Path("/api/v1/internal/backup/status")
@Produces(MediaType.APPLICATION_JSON)
public class BackupStatusResource {

    @ConfigProperty(name = "db-writer.db-path", defaultValue = "uniserve.db")
    String dbPath;

    // Optional: SmallRye rejects an empty String value; unset => "unconfigured (dev)".
    @ConfigProperty(name = "backup.destination")
    java.util.Optional<String> destination;

    @GET
    public Map<String, Object> status() {
        File db = new File(dbPath);
        long sizeKb = db.exists() ? Math.round(db.length() / 1024.0) : 0;

        Map<String, Object> body = new LinkedHashMap<>();
        // No backup has run in this environment (sidecar is k8s-only).
        body.put("lastBackup", null);
        body.put("backupSizeKb", sizeKb);
        body.put("destination", destination.filter(s -> !s.isBlank()).orElse("unconfigured (dev)"));
        return body;
    }
}
