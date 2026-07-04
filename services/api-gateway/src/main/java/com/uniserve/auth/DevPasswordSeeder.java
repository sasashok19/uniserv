package com.uniserve.auth;

import io.quarkus.elytron.security.common.BcryptUtil;
import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.util.Map;

/**
 * Dev-only: replaces the placeholder password hashes in the seed data with real
 * bcrypt hashes for the documented dev accounts, so login works out of the box
 * (Features 05 seed + 11 auth). No-op outside development; never blocks startup.
 */
@ApplicationScoped
public class DevPasswordSeeder {

    private static final Logger LOG = Logger.getLogger(DevPasswordSeeder.class);

    private static final Map<String, String> DEV_ACCOUNTS = Map.of(
            "admin@tneb.demo", "Admin@123",
            "lead@tneb.demo", "Lead@123",
            "agent@tneb.demo", "Agent@123");

    @Inject
    DbWriterClient db;

    @ConfigProperty(name = "app.env", defaultValue = "development")
    String appEnv;

    void onStart(@Observes StartupEvent event) {
        if (!"development".equals(appEnv)) {
            return;
        }
        for (Map.Entry<String, String> account : DEV_ACCOUNTS.entrySet()) {
            try {
                db.findAgentByEmail(account.getKey()).ifPresent(agent -> {
                    String hash = String.valueOf(agent.get("password_hash"));
                    if (hash == null || !hash.startsWith("$2")) {
                        db.updateAgent(String.valueOf(agent.get("id")),
                                Map.of("passwordHash", BcryptUtil.bcryptHash(account.getValue())));
                        LOG.infof("Dev password set for %s", account.getKey());
                    }
                });
            } catch (Exception e) {
                LOG.warnf("Dev password reseed failed for %s: %s", account.getKey(), e.getMessage());
            }
        }
    }
}
