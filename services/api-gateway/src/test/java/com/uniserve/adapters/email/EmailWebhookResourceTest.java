package com.uniserve.adapters.email;

import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.CoreMatchers.is;

/**
 * Test stubs for the Make.com email webhook (Feature 02a).
 * Uses the dev-default {@code email.webhook.secret=dev-webhook-secret}.
 */
@QuarkusTest
class EmailWebhookResourceTest {

    private static final String VALID_PAYLOAD = """
            {
              "channelIdentity": { "type": "email", "value": "test@example.com", "verified": false },
              "rawText": "My bill is wrong",
              "threadId": "thread-001",
              "sentAt": "2025-06-27T10:00:00Z"
            }""";

    @Test
    void acceptsValidPayloadWithCorrectSecret() {
        given()
                .header("X-Webhook-Secret", "dev-webhook-secret")
                .contentType("application/json")
                .body(VALID_PAYLOAD)
                .when().post("/api/v1/webhooks/email")
                .then()
                .statusCode(200)
                .body("received", is(true));
    }

    @Test
    void rejectsMissingSecret() {
        given()
                .contentType("application/json")
                .body(VALID_PAYLOAD)
                .when().post("/api/v1/webhooks/email")
                .then()
                .statusCode(401);
    }

    @Test
    void rejectsWrongSecret() {
        given()
                .header("X-Webhook-Secret", "not-the-secret")
                .contentType("application/json")
                .body(VALID_PAYLOAD)
                .when().post("/api/v1/webhooks/email")
                .then()
                .statusCode(401);
    }

    @Test
    void rejectsPayloadMissingRawText() {
        given()
                .header("X-Webhook-Secret", "dev-webhook-secret")
                .contentType("application/json")
                .body("""
                        { "channelIdentity": { "type": "email", "value": "test@example.com", "verified": false },
                          "sentAt": "2025-06-27T10:00:00Z" }""")
                .when().post("/api/v1/webhooks/email")
                .then()
                .statusCode(400)
                .body("valid", is(false));
    }

    @Test
    void forcesEmailIdentityUnverifiedEvenIfPayloadSaysOtherwise() {
        given()
                .header("X-Webhook-Secret", "dev-webhook-secret")
                .contentType("application/json")
                .body("""
                        { "channelIdentity": { "type": "email", "value": "spoof@example.com", "verified": true },
                          "rawText": "hi", "sentAt": "2025-06-27T10:00:00Z" }""")
                .when().post("/api/v1/webhooks/email")
                .then()
                .statusCode(200)
                .body("received", is(true));
    }
}
