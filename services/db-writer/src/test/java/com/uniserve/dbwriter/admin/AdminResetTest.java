package com.uniserve.dbwriter.admin;

import io.quarkus.hibernate.orm.panache.Panache;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import jakarta.transaction.Transactional;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * What a tenant reset does and — more importantly — does not destroy.
 *
 * Every test runs against its own throwaway tenant. A reset deletes everything
 * for the tenant it is given, and {@code @QuarkusTest} writes to the persistent
 * gitignored {@code uniserve.db} shared with every other test in the suite, so
 * resetting the real {@code t1} here would wipe data those tests count on.
 *
 * That same constraint is why {@code doReset} takes the preserved-agent list as
 * a parameter: agent ids are the primary key, so a test cannot create its own
 * "a2" to sit alongside the seeded one.
 */
@QuarkusTest
class AdminResetTest {

    @Inject
    AdminResetService reset;

    private String tenant;

    private String newTenant() {
        tenant = "reset-test-" + UUID.randomUUID();
        exec("insert into tenants(id, name, slug, config_json) values (?1, ?2, ?3, ?4)",
             tenant, "Reset Test", tenant, "{\"whatsappMenu\":{\"companyName\":\"Configured Co\"}}");
        return tenant;
    }

    private String agent(String role) {
        String id = "agent-" + UUID.randomUUID();
        exec("insert into agents(id, tenant_id, name, email, password_hash, role) "
             + "values (?1, ?2, ?3, ?4, ?5, ?6)",
             id, tenant, "Agent " + role, id + "@example.com", "hash", role);
        return id;
    }

    private String citizen() {
        String id = "identity-" + UUID.randomUUID();
        exec("insert into identity_profiles(id, tenant_id, master_id, name) values (?1, ?2, ?3, ?4)",
             id, tenant, UUID.randomUUID().toString(), "Seed Citizen");
        return id;
    }

    @Transactional
    void exec(String sql, Object... params) {
        var query = Panache.getEntityManager().createNativeQuery(sql);
        for (int i = 0; i < params.length; i++) {
            query.setParameter(i + 1, params[i]);
        }
        query.executeUpdate();
    }

    @Transactional
    Object scalar(String sql, Object... params) {
        var query = Panache.getEntityManager().createNativeQuery(sql);
        for (int i = 0; i < params.length; i++) {
            query.setParameter(i + 1, params[i]);
        }
        List<?> rows = query.getResultList();
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Object agentRole(String id) {
        return scalar("select role from agents where id = ?1", id);
    }

    private long countIn(String table) {
        return ((Number) scalar("select count(*) from " + table + " where tenant_id = ?1", tenant))
                .longValue();
    }

    // ---- staff -----------------------------------------------------------

    @Test
    void theDefaultStaffAccountsSurviveAlongsideTheAdminWhoAskedForTheReset() {
        newTenant();
        String admin = agent("admin");
        String seededLead = agent("lead");
        String seededField = agent("agent");
        String addedLater = agent("agent");

        reset.doReset(tenant, admin, List.of(seededLead, seededField));

        assertNotNull(agentRole(admin), "the admin performing the reset must survive");
        assertEquals("lead", agentRole(seededLead), "the default Lead Agent must survive");
        assertEquals("agent", agentRole(seededField), "the default Field Agent must survive");
        assertNull(agentRole(addedLater), "an account added since setup is data, and goes");
    }

    @Test
    void withNothingPreservedOnlyTheCallerSurvives() {
        // `not in ()` is invalid SQL, so the empty case has to be folded into
        // the caller's id rather than left to build a broken statement.
        newTenant();
        String admin = agent("admin");
        String other = agent("agent");

        reset.doReset(tenant, admin, List.of());

        assertNotNull(agentRole(admin));
        assertNull(agentRole(other));
    }

    @Test
    void theRealResetPreservesTheSeededStaffIds() {
        // The wiring the endpoint actually uses, asserted without running a
        // reset on t1: these are the ids V3 creates, and nothing re-inserts
        // them if they are deleted (INSERT OR IGNORE + an applied migration).
        assertTrue(AdminResetService.SEED_AGENT_IDS.containsAll(List.of("a1", "a2", "a3")));
    }

    // ---- data ------------------------------------------------------------

    @Test
    void citizenProfilesAreDeletedIncludingSeededOnes() {
        // Deliberate: citizens are data, they come back the moment anyone
        // messages in, and a stale demo citizen in a fresh tenant is clutter.
        newTenant();
        String admin = agent("admin");
        citizen();
        citizen();

        reset.doReset(tenant, admin, AdminResetService.SEED_AGENT_IDS);

        assertEquals(0, countIn("identity_profiles"));
    }

    @Test
    void theUnroutedQueueIsClearedToo() {
        // It was not, until this test. Rows survived a reset holding
        // resolved_ticket_id / resolved_by pointing at deleted rows.
        newTenant();
        String admin = agent("admin");
        exec("insert into unrouted_messages(id, tenant_id, channel, channel_identity_value, content) "
             + "values (?1, ?2, ?3, ?4, ?5)",
             "unrouted-" + UUID.randomUUID(), tenant, "whatsapp", "+919999999999", "hi");

        assertEquals(1, countIn("unrouted_messages"));
        reset.doReset(tenant, admin, AdminResetService.SEED_AGENT_IDS);

        assertEquals(0, countIn("unrouted_messages"));
    }

    @Test
    void theTenantsConfigurationIsNeverTouched() {
        // A reset clears a tenant's DATA. It is not a factory reset of its
        // setup, and must not quietly discard tuned WhatsApp menu wording.
        newTenant();
        String admin = agent("admin");

        reset.doReset(tenant, admin, AdminResetService.SEED_AGENT_IDS);

        assertEquals("{\"whatsappMenu\":{\"companyName\":\"Configured Co\"}}",
                     scalar("select config_json from tenants where id = ?1", tenant));
    }

    @Test
    void theResetIsAudited() {
        newTenant();
        String admin = agent("admin");

        Map<String, Object> counts = reset.doReset(tenant, admin, AdminResetService.SEED_AGENT_IDS);

        assertNotNull(counts.get("agents"));
        assertEquals("tenant.reset",
                     scalar("select event_type from ticket_events where tenant_id = ?1", tenant));
    }
}
