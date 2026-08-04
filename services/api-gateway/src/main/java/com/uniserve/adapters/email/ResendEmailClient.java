package com.uniserve.adapters.email;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.uniserve.adapters.SendResult;
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

    /**
     * Send via Resend's API. Throws on failure (caller/Quarkus error handler
     * treats that the same as an SMTP send failure).
     *
     * @param messageId the Message-ID we want this mail to carry (Feature 24) —
     * set as a custom header and returned, because Resend's own response
     * {@code id} is an internal handle, not the RFC 5322 header a citizen's
     * reply will quote back in {@code In-Reply-To}.
     */
    public SendResult send(String toAddress, String subject, String body,
                           String inReplyToMessageId, String messageId) {
        if (apiKey.isEmpty() || apiKey.get().isBlank()) {
            throw new IllegalStateException("RESEND_API_KEY is not set but EMAIL_PROVIDER=resend");
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("from", fromAddress);
        payload.put("to", List.of(toAddress));
        payload.put("subject", subject);
        payload.put("text", body);
        payload.put("headers", buildHeaders(inReplyToMessageId, messageId));

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
            LOG.infof("Email reply sent via Resend to=%s subject=%s messageId=%s",
                    toAddress, subject, messageId);
            return new SendResult(true, messageId);
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new RuntimeException("Resend API call failed: " + e.getMessage(), e);
        }
    }

    /**
     * Threading headers, angle-bracketed as RFC 5322 requires on the wire —
     * they are stored and compared unbracketed everywhere else in the codebase
     * (see {@code EmailAdapter.extractMessageId}). Package-private for tests.
     */
    static Map<String, String> buildHeaders(String inReplyToMessageId, String messageId) {
        Map<String, String> headers = new LinkedHashMap<>();
        if (messageId != null && !messageId.isBlank()) {
            headers.put("Message-ID", bracket(messageId));
        }
        if (inReplyToMessageId != null && !inReplyToMessageId.isBlank()) {
            headers.put("In-Reply-To", bracket(inReplyToMessageId));
            headers.put("References", bracket(inReplyToMessageId));
        }
        return headers;
    }

    private static String bracket(String id) {
        return id.startsWith("<") ? id : "<" + id + ">";
    }
}
