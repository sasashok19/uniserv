package com.uniserve.dbwriter.util;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;

/**
 * Timestamp formatting matching SQLite's {@code datetime('now')} output
 * ({@code yyyy-MM-dd HH:mm:ss}, UTC). Entities set these explicitly (via JPA
 * lifecycle callbacks) since Hibernate INSERT/UPDATE statements list every
 * mapped column and would otherwise overwrite the schema's column defaults
 * with NULL.
 */
public final class SqliteTime {

    private static final DateTimeFormatter FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneOffset.UTC);

    private SqliteTime() {
    }

    public static String now() {
        return FORMAT.format(Instant.now());
    }

    public static String plusHours(int hours) {
        return FORMAT.format(Instant.now().plus(hours, ChronoUnit.HOURS));
    }

    public static String minusDays(int days) {
        return FORMAT.format(Instant.now().minus(days, ChronoUnit.DAYS));
    }
}
