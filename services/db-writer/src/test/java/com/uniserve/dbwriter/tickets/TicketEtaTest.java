package com.uniserve.dbwriter.tickets;

import com.uniserve.dbwriter.common.ApiException;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 26: the ETA accept/reject truth table. Pure functions, no database,
 * no Quarkus boot — the same style as {@link TicketServiceTest}.
 */
class TicketEtaTest {

    private static final DateTimeFormatter STORAGE =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneOffset.UTC);

    private static String daysFromNow(int days) {
        return STORAGE.format(Instant.now().plus(days, ChronoUnit.DAYS)).substring(0, 10);
    }

    // ---- accepted shapes -------------------------------------------------

    @Test
    void bareDateBecomesEndOfThatDay() {
        String date = daysFromNow(3);
        assertEquals(date + " 23:59:59", TicketEta.normalise(date),
                "a bare date is a promise for the whole day, not for its first second");
    }

    @Test
    void fullTimestampIsKeptExactly() {
        String date = daysFromNow(2);
        assertEquals(date + " 14:30:00", TicketEta.normalise(date + " 14:30:00"));
    }

    @Test
    void secondsAreOptional() {
        String date = daysFromNow(2);
        assertEquals(date + " 14:30:00", TicketEta.normalise(date + " 14:30"));
    }

    @Test
    void isoSeparatorIsAccepted() {
        String date = daysFromNow(2);
        assertEquals(date + " 09:00:00", TicketEta.normalise(date + "T09:00:00"));
    }

    @Test
    void isoWithZuluIsAcceptedAndStoredAsUtc() {
        String date = daysFromNow(2);
        assertEquals(date + " 09:00:00", TicketEta.normalise(date + "T09:00:00Z"),
                "a browser sending new Date().toISOString() must not be rejected");
    }

    @Test
    void offsetIsConvertedToUtcRatherThanTruncated() {
        String date = daysFromNow(4);
        // +05:30 (IST, the deployment's actual timezone) at 12:00 is 06:30 UTC.
        assertEquals(date + " 06:30:00", TicketEta.normalise(date + "T12:00:00+05:30"));
    }

    @Test
    void surroundingWhitespaceIsTolerated() {
        String date = daysFromNow(3);
        assertEquals(date + " 23:59:59", TicketEta.normalise("  " + date + "  "));
    }

    // ---- "not supplied" is not "invalid" ---------------------------------

    @Test
    void nullIsNullNotAnError() {
        assertNull(TicketEta.normalise(null),
                "only the caller knows whether a missing ETA is allowed here");
    }

    @Test
    void blankIsTreatedAsNotSupplied() {
        assertNull(TicketEta.normalise(""));
        assertNull(TicketEta.normalise("   "));
    }

    // ---- rejected --------------------------------------------------------

    @Test
    void freeTextIsRejected() {
        ApiException e = assertThrows(ApiException.class, () -> TicketEta.normalise("next tuesday"));
        assertEquals(422, e.status());
        assertEquals("ETA_INVALID", e.code());
    }

    @Test
    void ambiguousDayFirstFormatIsRejectedRatherThanGuessed() {
        // 03/04/2027 is 3 April in India and 4 March in the US. Guessing would
        // put a wrong promise in front of a citizen; failing makes the client fix it.
        assertThrows(ApiException.class, () -> TicketEta.normalise("03/04/2027"));
    }

    @Test
    void impossibleDateIsRejected() {
        assertThrows(ApiException.class, () -> TicketEta.normalise("2027-02-30"));
    }

    @Test
    void pastEtaIsRejected() {
        ApiException e = assertThrows(ApiException.class, () -> TicketEta.normalise("2020-01-01"));
        assertEquals(422, e.status());
        assertEquals("ETA_IN_PAST", e.code());
    }

    @Test
    void mistypedYearIsRejectedRatherThanStoredForever() {
        // The realistic typo: 2226 for 2026. Nothing downstream would ever
        // question it, and a citizen would be quoted a 200-year ETA.
        ApiException e = assertThrows(ApiException.class, () -> TicketEta.normalise("2226-08-18"));
        assertEquals("ETA_TOO_FAR", e.code());
    }

    @Test
    void storedFormAlwaysSortsLexicographically() {
        // Every timestamp column in this schema is compared as a string.
        String near = TicketEta.normalise(daysFromNow(2));
        String far = TicketEta.normalise(daysFromNow(40));
        assertTrue(near.compareTo(far) < 0,
                "a mixed storage format would sort wrongly instead of failing loudly");
    }

    // ---- the migration is part of the contract ---------------------------

    @Test
    void migrationAddsBothColumnsAndBackfillsFirstTransition() throws Exception {
        String v14 = new String(getClass().getClassLoader()
                .getResourceAsStream("db/migration/V14__ticket_eta.sql").readAllBytes());
        assertTrue(v14.contains("ADD COLUMN eta_at"), "V14 must add eta_at");
        assertTrue(v14.contains("ADD COLUMN first_transition_at"), "V14 must add first_transition_at");
        assertTrue(v14.contains("status.%"),
                "existing tickets must be backfilled from the audit trail, or every one of "
                        + "them demands an ETA the next time an agent touches it");
    }
}
