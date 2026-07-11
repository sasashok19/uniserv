package com.uniserve.adapters.email;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for the email webhook's X-Webhook-Secret validation (Feature 02a). */
class EmailWebhookSecretValidatorTest {

    @Test
    void acceptsMatchingSecret() {
        assertTrue(EmailWebhookSecretValidator.isValid("dev-webhook-secret", "dev-webhook-secret"));
    }

    @Test
    void rejectsMismatchedSecret() {
        assertFalse(EmailWebhookSecretValidator.isValid("wrong-secret", "dev-webhook-secret"));
    }

    @Test
    void rejectsMissingHeader() {
        assertFalse(EmailWebhookSecretValidator.isValid(null, "dev-webhook-secret"));
    }

    @Test
    void rejectsWhenExpectedSecretUnconfigured() {
        assertFalse(EmailWebhookSecretValidator.isValid("anything", ""));
        assertFalse(EmailWebhookSecretValidator.isValid("anything", null));
    }
}
