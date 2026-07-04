package com.uniserve.adapters.whatsapp;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * Validates Meta's {@code X-Hub-Signature-256} header (HMAC-SHA256 of the raw
 * request body, keyed by the app secret) for the WhatsApp webhook (Feature 02b).
 *
 * <p>In development a fixed bypass token ({@code sha256=test_bypass_in_dev}) is
 * accepted so the documented test stub can exercise the endpoint without signing.
 */
public final class WhatsAppSignatureValidator {

    static final String DEV_BYPASS = "sha256=test_bypass_in_dev";

    private WhatsAppSignatureValidator() {
    }

    /**
     * @param signatureHeader value of the {@code X-Hub-Signature-256} header
     * @param body            the exact raw request body
     * @param appSecret       the tenant/app HMAC secret (may be blank)
     * @param devMode         true when {@code APP_ENV=development}
     */
    public static boolean isValid(String signatureHeader, String body, String appSecret, boolean devMode) {
        if (devMode && DEV_BYPASS.equals(signatureHeader)) {
            return true;
        }
        if (signatureHeader == null || !signatureHeader.startsWith("sha256=")) {
            return false;
        }
        if (appSecret == null || appSecret.isBlank()) {
            // No secret configured and not the dev bypass: cannot verify.
            return false;
        }
        String expected = "sha256=" + hmacSha256(appSecret, body);
        // Constant-time comparison to avoid timing leaks.
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                signatureHeader.getBytes(StandardCharsets.UTF_8));
    }

    static String hmacSha256(String secret, String body) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal(body.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                hex.append(Character.forDigit((b >> 4) & 0xF, 16));
                hex.append(Character.forDigit(b & 0xF, 16));
            }
            return hex.toString();
        } catch (Exception e) {
            throw new IllegalStateException("HMAC-SHA256 computation failed", e);
        }
    }
}
