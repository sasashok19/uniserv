package com.uniserve.adapters.whatsapp;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for WhatsApp HMAC signature validation (Feature 02b). */
class WhatsAppSignatureValidatorTest {

    private static final String BODY = "{\"object\":\"whatsapp_business_account\"}";
    private static final String SECRET = "super-secret";

    @Test
    void acceptsDevBypassInDevelopment() {
        assertTrue(WhatsAppSignatureValidator.isValid(
                "sha256=test_bypass_in_dev", BODY, "", true));
    }

    @Test
    void rejectsDevBypassOutsideDevelopment() {
        assertFalse(WhatsAppSignatureValidator.isValid(
                "sha256=test_bypass_in_dev", BODY, SECRET, false));
    }

    @Test
    void acceptsValidHmacSignature() {
        String sig = "sha256=" + WhatsAppSignatureValidator.hmacSha256(SECRET, BODY);
        assertTrue(WhatsAppSignatureValidator.isValid(sig, BODY, SECRET, false));
    }

    @Test
    void rejectsInvalidHmacSignature() {
        assertFalse(WhatsAppSignatureValidator.isValid(
                "sha256=deadbeef", BODY, SECRET, true));
    }

    @Test
    void rejectsMissingSignature() {
        assertFalse(WhatsAppSignatureValidator.isValid(null, BODY, SECRET, true));
    }
}
