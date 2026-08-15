package com.uniserve.adapters.whatsapp;

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
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Sends outbound WhatsApp replies via Meta's Graph API (Feature 02b outbound).
 * The counterpart to {@link com.uniserve.adapters.email.EmailAdapter#sendReply}:
 * inbound is handled by {@link WhatsAppWebhookResource}, this class is outbound-only.
 *
 * <p>{@code graphApiBaseUrl} is overridable (test seam — points at a local stub
 * server in {@code WhatsAppAdapterTest}); production always uses the default.
 */
@ApplicationScoped
public class WhatsAppAdapter {

    private static final Logger LOG = Logger.getLogger(WhatsAppAdapter.class);

    @Inject
    ObjectMapper mapper;

    @ConfigProperty(name = "whatsapp.access-token")
    Optional<String> accessToken;

    @ConfigProperty(name = "whatsapp.phone-number-id")
    Optional<String> phoneNumberId;

    @ConfigProperty(name = "whatsapp.graph-api-base-url", defaultValue = "https://graph.facebook.com")
    String graphApiBaseUrl;

    @ConfigProperty(name = "whatsapp.api-version", defaultValue = "v21.0")
    String apiVersion;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10)).build();

    /**
     * Send a free-form text reply. {@code contextMessageId} — the citizen's
     * inbound wamid (Feature 15 parity, {@code origin_message_id}) — makes the
     * reply render as a quoted reply-to in WhatsApp when present; omitted otherwise.
     *
     * <p>Note (Meta's 24-hour customer service window): a free-form text message
     * can only be sent within 24h of the citizen's last inbound message; outside
     * that window Meta requires a pre-approved template message instead, and this
     * call fails with a Graph API error (not implemented — see docs/02b_ADAPTER_WHATSAPP.md).
     *
     * @return the send outcome including the wamid Meta assigned this message
     * (Feature 24) — recorded against the ticket_message row so a citizen's
     * swipe-reply to it resolves straight back to this ticket. Throws on
     * failure (caller decides whether that's fatal or best-effort, same
     * convention as {@code EmailAdapter}).
     */
    public SendResult sendReply(String toPhone, String body, String contextMessageId) {
        return sendReply(toPhone, body, contextMessageId, null, null);
    }

    /**
     * As above, but rendered as an <b>interactive reply-buttons</b> message when
     * {@code buttons} is non-empty (Feature 28) — tappable options instead of
     * "press 1", which is what a citizen on a phone expects.
     *
     * <p>Interactive messages are ordinary free-form messages as far as Meta's
     * 24-hour window is concerned: they are not templates, so the same window
     * rule above applies unchanged.
     *
     * @param buttons up to 3 entries of {@code {"id": ..., "title": ...}};
     *                more are dropped and over-long titles truncated rather than
     *                rejected, because Meta refuses the whole send otherwise and
     *                a clipped word beats no message
     * @param footer  the small grey line under the buttons, or null
     */
    public SendResult sendReply(String toPhone, String body, String contextMessageId,
                                List<Map<String, String>> buttons, String footer) {
        if (accessToken.isEmpty() || accessToken.get().isBlank()) {
            throw new IllegalStateException("WHATSAPP_ACCESS_TOKEN is not set");
        }
        if (phoneNumberId.isEmpty() || phoneNumberId.get().isBlank()) {
            throw new IllegalStateException("WHATSAPP_PHONE_NUMBER_ID is not set");
        }

        Map<String, Object> payload = buildPayload(toPhone, body, contextMessageId, buttons, footer);
        URI uri = URI.create(graphApiBaseUrl + "/" + apiVersion + "/" + phoneNumberId.get() + "/messages");

        try {
            String json = mapper.writeValueAsString(payload);
            HttpRequest req = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(15))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + accessToken.get())
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new RuntimeException("WhatsApp Graph API " + resp.statusCode() + ": " + resp.body());
            }
            String wamid = extractWamid(resp.body());
            LOG.infof("WhatsApp reply sent via Graph API to=%s wamid=%s", toPhone, wamid);
            return new SendResult(true, wamid);
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new RuntimeException("WhatsApp Graph API call failed: " + e.getMessage(), e);
        }
    }

    /**
     * The wamid out of a Graph API send response (Feature 24):
     * {@code {"messages":[{"id":"wamid.HBg..."}]}}.
     *
     * Never throws and never fails the send: the message HAS gone to the
     * citizen by this point, so an unexpected response shape must cost us the
     * routing shortcut, not the reply. Package-private for unit tests.
     */
    static String extractWamid(String responseBody) {
        try {
            com.fasterxml.jackson.databind.JsonNode id = new com.fasterxml.jackson.databind.ObjectMapper()
                    .readTree(responseBody == null ? "" : responseBody)
                    .path("messages").path(0).path("id");
            String wamid = id.isMissingNode() || id.isNull() ? null : id.asText(null);
            return wamid == null || wamid.isBlank() ? null : wamid;
        } catch (Exception e) {
            LOG.warnf("WhatsApp send succeeded but the wamid could not be read: %s", e.getMessage());
            return null;
        }
    }

    /** Pure payload construction (unit-tested without CDI/network). */
    static Map<String, Object> buildPayload(String toPhone, String body, String contextMessageId) {
        return buildPayload(toPhone, body, contextMessageId, null, null);
    }

    /** Meta's interactive reply-button limits. Exceeding any of them fails the
     * whole send, so they are enforced by truncation here rather than trusted. */
    static final int MAX_BUTTONS = 3;
    static final int MAX_BUTTON_TITLE = 20;
    static final int MAX_BODY = 1024;
    static final int MAX_FOOTER = 60;

    static Map<String, Object> buildPayload(String toPhone, String body, String contextMessageId,
                                            List<Map<String, String>> buttons, String footer) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("messaging_product", "whatsapp");
        payload.put("to", stripLeadingPlus(toPhone));

        if (buttons == null || buttons.isEmpty()) {
            payload.put("type", "text");
            payload.put("text", Map.of("body", body == null ? "" : body));
        } else {
            List<Map<String, Object>> replies = new ArrayList<>();
            for (Map<String, String> button : buttons.subList(0, Math.min(buttons.size(), MAX_BUTTONS))) {
                String title = trim(button.get("title"), MAX_BUTTON_TITLE);
                if (title.isEmpty()) {
                    continue;   // an unlabelled button is worse than one fewer
                }
                replies.add(Map.of("type", "reply", "reply",
                        Map.of("id", button.getOrDefault("id", title), "title", title)));
            }
            if (replies.isEmpty()) {
                // Nothing renderable — fall back to text rather than send a
                // button message with no buttons, which Meta rejects.
                payload.put("type", "text");
                payload.put("text", Map.of("body", body == null ? "" : body));
                return withContext(payload, contextMessageId);
            }
            Map<String, Object> interactive = new LinkedHashMap<>();
            interactive.put("type", "button");
            interactive.put("body", Map.of("text", trim(body, MAX_BODY)));
            String cleanFooter = trim(footer, MAX_FOOTER);
            if (!cleanFooter.isEmpty()) {
                interactive.put("footer", Map.of("text", cleanFooter));
            }
            interactive.put("action", Map.of("buttons", replies));
            payload.put("type", "interactive");
            payload.put("interactive", interactive);
        }
        return withContext(payload, contextMessageId);
    }

    private static Map<String, Object> withContext(Map<String, Object> payload, String contextMessageId) {
        if (contextMessageId != null && !contextMessageId.isBlank()) {
            payload.put("context", Map.of("message_id", contextMessageId));
        }
        return payload;
    }

    private static String trim(String value, int max) {
        if (value == null) {
            return "";
        }
        String trimmed = value.trim();
        return trimmed.length() > max ? trimmed.substring(0, max) : trimmed;
    }

    /** Graph API expects the destination in E.164 digits without a leading '+'. */
    static String stripLeadingPlus(String phone) {
        return phone != null && phone.startsWith("+") ? phone.substring(1) : phone;
    }
}
