package com.uniserve.adapters.email;

import com.uniserve.adapters.ChannelIdentity;
import com.uniserve.adapters.ChannelMessagePublisher;
import com.uniserve.adapters.ChannelMessageReceived;
import com.uniserve.adapters.EventValidator;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.HeaderParam;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * Inbound email webhook (Feature 02a, Phase 1): Make.com watches the mailbox
 * (Gmail/Outlook) and POSTs the parsed message here — this gateway does no
 * IMAP polling. Validates {@code X-Webhook-Secret}, fills in the envelope
 * fields Make.com doesn't send, validates the result against the adapter
 * contract (02f), and publishes to Valkey off the request thread so the
 * response returns immediately.
 */
@Path("/api/v1/webhooks/email")
public class EmailWebhookResource {

    private static final Logger LOG = Logger.getLogger(EmailWebhookResource.class);

    @Inject
    ChannelMessagePublisher publisher;

    @ConfigProperty(name = "email.webhook.secret", defaultValue = "dev-webhook-secret")
    String webhookSecret;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String defaultTenantId;

    /** Wire shape Make.com posts: a partial {@code ChannelMessageReceived} (Feature 02f). */
    public record EmailWebhookPayload(
            String tenantId,
            ChannelIdentity channelIdentity,
            String rawText,
            List<String> rawMediaUrls,
            String languageHint,
            String threadId,
            String inReplyTo,
            String sentAt) {
    }

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response receive(@HeaderParam("X-Webhook-Secret") String secret, EmailWebhookPayload payload) {
        if (!EmailWebhookSecretValidator.isValid(secret, webhookSecret)) {
            LOG.warn("Email webhook rejected: invalid or missing X-Webhook-Secret");
            return error(401, "UNAUTHORIZED", "Invalid webhook secret");
        }

        ChannelMessageReceived event = toEvent(payload);
        List<String> errors = EventValidator.validate(event);
        if (!errors.isEmpty()) {
            return Response.status(Response.Status.BAD_REQUEST)
                    .entity(Map.of("valid", false, "errors", errors))
                    .build();
        }

        CompletableFuture.runAsync(() -> {
            try {
                publisher.publish(event);
            } catch (Exception e) {
                LOG.errorf(e, "Failed to publish email webhook event %s", event.id());
            }
        });

        return Response.ok(Map.of("received", true)).build();
    }

    /**
     * Builds the canonical event, backfilling id/timestamp/receivedAt/traceId
     * (Make.com doesn't send these) and forcing {@code channelIdentity} to the
     * 02f contract rule for email: {@code type=email, verified=false}.
     */
    private ChannelMessageReceived toEvent(EmailWebhookPayload payload) {
        String now = Instant.now().toString();
        if (payload == null) {
            return new ChannelMessageReceived(
                    UUID.randomUUID().toString(), defaultTenantId, ChannelMessageReceived.TYPE, now,
                    "email", null, null, List.of(), null, null, null, null, now,
                    UUID.randomUUID().toString());
        }

        ChannelIdentity identity = payload.channelIdentity() == null
                ? null
                : new ChannelIdentity("email", payload.channelIdentity().value(), false);
        String tenantId = payload.tenantId() == null || payload.tenantId().isBlank()
                ? defaultTenantId : payload.tenantId();

        return new ChannelMessageReceived(
                UUID.randomUUID().toString(),
                tenantId,
                ChannelMessageReceived.TYPE,
                now,
                "email",
                identity,
                payload.rawText(),
                payload.rawMediaUrls() == null ? List.of() : payload.rawMediaUrls(),
                payload.languageHint(),
                payload.threadId(),
                payload.inReplyTo(),
                payload.sentAt(),
                now,
                UUID.randomUUID().toString());
    }

    private Response error(int status, String code, String message) {
        return Response.status(status)
                .entity(Map.of("error", Map.of("code", code, "message", message)))
                .build();
    }
}
