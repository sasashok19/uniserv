package com.uniserve.adapters.email;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Sends outbound email via Resend's HTTPS API (port 443) instead of raw SMTP.
 * Render's free-tier web services block outbound SMTP (ports 25/465/587)
 * entirely as of their 2025-09-26 network policy change — no client-side
 * timeout or port change works around that, since the TCP connection itself
 * never completes. Resend (or any HTTP-based provider) sidesteps it since
 * it's a normal HTTPS call.
 *
 * <p>Selected via {@code EMAIL_PROVIDER=resend} (see {@link EmailAdapter#sendReply});
 * flip back to {@code EMAIL_PROVIDER=smtp} if/when upgrading to a paid Render
 * plan lifts the SMTP block and direct Gmail SMTP is preferred again.
 */
@ApplicationScoped
public class ResendEmailClient {

    private static final Logger LOG = Logger.getLogger(ResendEmailClient.class);
    private static final URI RESEND_API = URI.create("https://api.resend.com/emails");

    @Inject
    ObjectMapper mapper;

    @ConfigProperty(name = "resend.api-key")
    java.util.Optional<String> apiKey;

    @ConfigProperty(name = "resend.from-address", defaultValue = "onboarding@resend.dev")
    String fromAddress;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10)).build();

    /** Send via Resend's API. Returns true on a 2xx response; throws on failure
     * (caller/Quarkus error handler treats that the same as an SMTP send failure). */
    public boolean send(String toAddress, String subject, String body, String inReplyToMessageId) {
        if (apiKey.isEmpty() || apiKey.get().isBlank()) {
            throw new IllegalStateException("RESEND_API_KEY is not set but EMAIL_PROVIDER=resend");
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("from", fromAddress);
        payload.put("to", List.of(toAddress));
        payload.put("subject", subject);
        payload.put("text", body);
        if (inReplyToMessageId != null && !inReplyToMessageId.isBlank()) {
            payload.put("headers", Map.of(
                    "In-Reply-To", inReplyToMessageId,
                    "References", inReplyToMessageId));
        }

        try {
            String json = mapper.writeValueAsString(payload);
            HttpRequest req = HttpRequest.newBuilder(RESEND_API)
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + apiKey.get())
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new RuntimeException("Resend API " + resp.statusCode() + ": " + resp.body());
            }
            LOG.infof("Email reply sent via Resend to=%s subject=%s", toAddress, subject);
            return true;
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new RuntimeException("Resend API call failed: " + e.getMessage(), e);
        }
    }
}
