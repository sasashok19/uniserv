package com.uniserve.adapters.email;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * Validates the {@code X-Webhook-Secret} header on the Make.com email webhook
 * (Feature 02a). Pure, constant-time comparison — no framework dependencies.
 */
public final class EmailWebhookSecretValidator {

    private EmailWebhookSecretValidator() {
    }

    public static boolean isValid(String headerValue, String expectedSecret) {
        if (headerValue == null || expectedSecret == null || expectedSecret.isBlank()) {
            return false;
        }
        return MessageDigest.isEqual(
                headerValue.getBytes(StandardCharsets.UTF_8),
                expectedSecret.getBytes(StandardCharsets.UTF_8));
    }
}
