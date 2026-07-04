package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uniserve.adapters.ChannelMessagePublisher;
import com.uniserve.adapters.ChannelMessageReceived;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.HeaderParam;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.util.Optional;

/**
 * WhatsApp Business webhook (Feature 02b).
 *
 * <ul>
 *   <li>{@code GET}  — Meta {@code hub.verify_token} subscription handshake.</li>
 *   <li>{@code POST} — inbound messages; HMAC-validated, parsed to the canonical
 *       event and published to the bus. Always answers fast (200/401).</li>
 * </ul>
 */
@Path("/api/v1/webhooks/whatsapp")
public class WhatsAppWebhookResource {

    private static final Logger LOG = Logger.getLogger(WhatsAppWebhookResource.class);

    @Inject
    ObjectMapper mapper;

    @Inject
    ChannelMessagePublisher publisher;

    @ConfigProperty(name = "whatsapp.verify-token")
    String verifyToken;

    @ConfigProperty(name = "whatsapp.app-secret")
    Optional<String> appSecret;

    @ConfigProperty(name = "app.env", defaultValue = "development")
    String appEnv;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String tenantId;

    /** Meta subscription handshake: echo the challenge when the verify token matches. */
    @GET
    @Produces(MediaType.TEXT_PLAIN)
    public Response verify(@QueryParam("hub.mode") String mode,
                           @QueryParam("hub.verify_token") String token,
                           @QueryParam("hub.challenge") String challenge) {
        if ("subscribe".equals(mode) && verifyToken != null && verifyToken.equals(token)) {
            return Response.ok(challenge).build();
        }
        return Response.status(Response.Status.FORBIDDEN).build();
    }

    /** Inbound messages. Validates the signature, then parses and publishes. */
    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response receive(@HeaderParam("X-Hub-Signature-256") String signature, String body) {
        boolean devMode = "development".equals(appEnv);
        if (!WhatsAppSignatureValidator.isValid(signature, body, appSecret.orElse(""), devMode)) {
            LOG.warn("WhatsApp webhook rejected: invalid X-Hub-Signature-256");
            return Response.status(Response.Status.UNAUTHORIZED).build();
        }

        int published = 0;
        try {
            JsonNode root = mapper.readTree(body);
            for (ChannelMessageReceived message : WhatsAppParser.parse(root, tenantId)) {
                publisher.publish(message);
                published++;
            }
        } catch (Exception e) {
            // Meta requires a prompt 200 to avoid retries storms; log and swallow parse errors.
            LOG.errorf(e, "Failed to process WhatsApp webhook payload");
        }
        LOG.debugf("WhatsApp webhook processed, published=%d", published);
        return Response.ok().build();
    }
}
