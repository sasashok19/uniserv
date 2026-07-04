package com.uniserve.adapters;

import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Seeds representative channel events into Valkey on {@code APP_ENV=development}
 * (Features 02a/02b "Mock Data Seed"). Lets the AI pipeline and inspection
 * endpoints have data to work with before any real message arrives. No-op outside
 * development, and failures never block startup.
 */
@ApplicationScoped
public class DevDataSeeder {

    private static final Logger LOG = Logger.getLogger(DevDataSeeder.class);

    @Inject
    ChannelMessagePublisher publisher;

    @ConfigProperty(name = "app.env", defaultValue = "development")
    String appEnv;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String tenantId;

    @ConfigProperty(name = "dev.seed.enabled", defaultValue = "true")
    boolean seedEnabled;

    void onStart(@Observes StartupEvent event) {
        if (!"development".equals(appEnv) || !seedEnabled) {
            return;
        }
        try {
            seedEmails();
            seedWhatsApp();
            LOG.info("Dev data seed complete: 5 email + 5 whatsapp channel events published");
        } catch (Exception e) {
            LOG.errorf(e, "Dev data seeding failed (non-fatal)");
        }
    }

    private void seedEmails() {
        publisher.publish(email("john@example.com", "My electricity bill is double this month"));
        publisher.publish(email("meena@example.com", "Power outage in our area since morning"));
        publisher.publish(email("feedback@example.com", "Great service last week, thank you"));
        publisher.publish(email("anon@example.com", "I want to report an issue without sharing details"));
        publisher.publish(emailReply("john@example.com", "Following up on my earlier bill complaint", "seed-thread-001"));
    }

    private void seedWhatsApp() {
        publisher.publish(whatsapp("+919876543210", "My electricity bill is double this month"));
        publisher.publish(whatsapp("+919812345678", "My meter is faulty and showing wrong readings"));
        publisher.publish(whatsapp("+919800000001", "No response to my service request for 3 days"));
        publisher.publish(whatsapp("+919700000002", "Can I report something anonymously?"));
        publisher.publish(whatsapp("+919876543210", "Any update on my complaint?"));
    }

    private ChannelMessageReceived email(String from, String text) {
        return channelMessage("email", new ChannelIdentity("email", from, false), text, null);
    }

    private ChannelMessageReceived emailReply(String from, String text, String threadId) {
        return channelMessage("email", new ChannelIdentity("email", from, false), text, threadId);
    }

    private ChannelMessageReceived whatsapp(String phone, String text) {
        return channelMessage("whatsapp", new ChannelIdentity("phone", phone, true), text, null);
    }

    private ChannelMessageReceived channelMessage(String channel, ChannelIdentity identity,
                                                  String text, String threadId) {
        String nowIso = Instant.now().toString();
        return new ChannelMessageReceived(
                UUID.randomUUID().toString(),
                tenantId,
                ChannelMessageReceived.TYPE,
                nowIso,
                channel,
                identity,
                text,
                List.of(),
                null,
                threadId,
                threadId,
                nowIso,
                nowIso,
                UUID.randomUUID().toString());
    }
}
