package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;

/**
 * Parsing and validation for a ticket's ETA (Feature 26).
 *
 * Split out of {@link TicketService} as a pure function, the same way
 * {@code buildWhere} is, so the whole accept/reject truth table can be tested
 * without a database or a Quarkus boot — see {@code TicketEtaTest}.
 *
 * <p>The stored form is always {@code yyyy-MM-dd HH:mm:ss} UTC, matching every
 * other timestamp in this schema (see {@link com.uniserve.dbwriter.util.SqliteTime}),
 * because these columns are compared and sorted as strings and a mixed format
 * would sort wrongly rather than fail loudly.
 *
 * <p><b>A bare date means the END of that day.</b> An agent typing
 * {@code 2026-08-18} is promising "by the 18th", not "by midnight as the 18th
 * begins". Storing 00:00:00 would mark the ticket overdue for the entire day it
 * was actually due, which is the sort of off-by-one that quietly makes an
 * overdue report useless.
 */
public final class TicketEta {

    private static final DateTimeFormatter STORAGE =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneOffset.UTC);

    /** How far ahead an ETA may be. Anything beyond this is a typo, not a plan —
     * overwhelmingly a mistyped year (2226 for 2026), which would otherwise sit
     * in the database forever and be read out to a citizen as a promise. */
    private static final int MAX_YEARS_AHEAD = 5;

    private TicketEta() {
    }

    /**
     * Canonicalise an agent-supplied ETA, or throw {@link ApiException} 422.
     *
     * Accepts {@code yyyy-MM-dd}, {@code yyyy-MM-dd HH:mm[:ss]},
     * {@code yyyy-MM-ddTHH:mm[:ss]}, and full ISO-8601 with an offset or
     * {@code Z}. Returns null for null/blank input — "no ETA supplied" is a
     * distinct case from "an invalid ETA was supplied", and only the caller
     * knows whether the former is allowed here.
     */
    public static String normalise(Object raw) {
        if (raw == null) {
            return null;
        }
        String text = String.valueOf(raw).trim();
        if (text.isEmpty()) {
            return null;
        }

        Instant parsed = parse(text);
        if (parsed == null) {
            throw new ApiException(422, "ETA_INVALID",
                    "eta must be a date (yyyy-MM-dd) or timestamp (yyyy-MM-dd HH:mm:ss), got: " + text);
        }

        Instant now = Instant.now();
        if (parsed.isBefore(now)) {
            throw new ApiException(422, "ETA_IN_PAST",
                    "eta must be in the future, got: " + text);
        }
        if (parsed.isAfter(now.atOffset(ZoneOffset.UTC).plusYears(MAX_YEARS_AHEAD).toInstant())) {
            throw new ApiException(422, "ETA_TOO_FAR",
                    "eta must be within " + MAX_YEARS_AHEAD + " years, got: " + text);
        }
        return STORAGE.format(parsed);
    }

    /** Every accepted shape, most specific first. Null when none of them match. */
    private static Instant parse(String text) {
        // Full ISO-8601 with an offset/Z — what a JavaScript client sends if
        // nobody stops it (`new Date().toISOString()`).
        try {
            return OffsetDateTime.parse(text).toInstant();
        } catch (DateTimeParseException ignored) {
            // fall through
        }
        // Local date-time, with either separator and with seconds optional.
        String normalisedSeparator = text.replace('T', ' ');
        for (String pattern : new String[]{"yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"}) {
            try {
                return LocalDateTime.parse(normalisedSeparator, DateTimeFormatter.ofPattern(pattern))
                        .toInstant(ZoneOffset.UTC);
            } catch (DateTimeParseException ignored) {
                // fall through
            }
        }
        // Bare date -> end of that day. See the class javadoc.
        try {
            return LocalDate.parse(text).atTime(23, 59, 59).toInstant(ZoneOffset.UTC);
        } catch (DateTimeParseException ignored) {
            return null;
        }
    }
}
