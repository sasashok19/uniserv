package com.uniserve.dbwriter.identity;

import com.uniserve.dbwriter.common.ApiException;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Feature 29: the citizen correcting their own name or email from the WhatsApp
 * menu.
 *
 * Every earlier caller of {@code update} is an ENRICHMENT — a later channel
 * filling in a field we did not have — and must never clobber a confirmed
 * value. A citizen fixing a stale value is the exact opposite, and a correction
 * that silently does nothing is the very thing they were trying to fix. Hence
 * {@code overwrite: true} as an explicit opt-in rather than a change of
 * meaning for everyone.
 *
 * Data is randomised per test: {@code @QuarkusTest} writes to the persistent
 * gitignored {@code uniserve.db}, so a fixed email would pass once and then
 * collide with its own leftovers on the next run.
 */
@QuarkusTest
class IdentityOverwriteTest {

    @Inject
    IdentityService identities;

    private static final String TENANT = "t1";

    private static String unique(String prefix) {
        return prefix + "-" + UUID.randomUUID().toString().substring(0, 8);
    }

    private String create(String name, String email) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tenantId", TENANT);
        body.put("name", name);
        body.put("email", email);
        body.put("phone", unique("+9198"));
        return String.valueOf(identities.create(body).get("id"));
    }

    private static Map<String, Object> patch(String key, String value, boolean overwrite) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put(key, value);
        if (overwrite) {
            body.put("overwrite", true);
        }
        return body;
    }

    // ---- the enrichment contract, unchanged ------------------------------

    @Test
    void withoutTheFlagASetNameIsStillNeverClobbered() {
        String id = create("Ashok", unique("a") + "@example.com");

        Map<String, Object> updated = identities.update(id, patch("name", "Someone Else", false));

        assertEquals("Ashok", updated.get("name"),
                "enrichment must not let a later channel overwrite a confirmed value");
    }

    @Test
    void withoutTheFlagABlankFieldIsStillFilledIn() {
        String id = create(null, null);

        assertEquals("Ashok", identities.update(id, patch("name", "Ashok", false)).get("name"));
    }

    // ---- the correction path ---------------------------------------------

    @Test
    void withTheFlagTheCitizenCanCorrectTheirName() {
        String id = create("Ashok", unique("a") + "@example.com");

        assertEquals("Ashok Srinivasan",
                identities.update(id, patch("name", "Ashok Srinivasan", true)).get("name"));
    }

    @Test
    void withTheFlagTheCitizenCanCorrectTheirEmail() {
        String id = create("Ashok", unique("old") + "@example.com");
        String replacement = unique("new") + "@example.com";

        assertEquals(replacement, identities.update(id, patch("email", replacement, true)).get("email"));
    }

    @Test
    void anEmailAnotherIdentityAlreadyHoldsIsRejected() {
        // Not an edit — a silent reassignment of whoever owns those tickets.
        // Only a human can tell "I mistyped it last time" from "that is my
        // colleague's address", so this is a 409 rather than a merge.
        String taken = unique("taken") + "@example.com";
        create("Priya", taken);
        String id = create("Ashok", unique("a") + "@example.com");

        ApiException e = assertThrows(ApiException.class,
                () -> identities.update(id, patch("email", taken, true)));

        assertEquals(409, e.status());
        assertEquals("EMAIL_IN_USE", e.code());
    }

    @Test
    void resendingTheirOwnEmailIsNotACollision() {
        String mine = unique("mine") + "@example.com";
        String id = create("Ashok", mine);

        assertEquals(mine, identities.update(id, patch("email", mine, true)).get("email"));
    }

    @Test
    void theCollisionCheckIsScopedToTheOverwritePath() {
        // Enrichment has always been allowed to walk into a shared email — that
        // is the duplicate-identity case `merge` exists for — and tightening it
        // here would change a contract Feature 29 has no business changing.
        String taken = unique("taken") + "@example.com";
        create("Priya", taken);
        String id = create("Ashok", null);

        assertEquals(taken, identities.update(id, patch("email", taken, false)).get("email"));
    }
}
