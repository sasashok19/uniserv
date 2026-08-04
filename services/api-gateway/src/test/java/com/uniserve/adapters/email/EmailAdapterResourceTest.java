package com.uniserve.adapters.email;

import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Unit tests for {@link EmailAdapterResource#testSend}'s error handling. */
class EmailAdapterResourceTest {

    private EmailAdapterResource newResource(EmailAdapter emailAdapter) {
        EmailAdapterResource resource = new EmailAdapterResource();
        resource.emailAdapter = emailAdapter;
        return resource;
    }

    @Test
    void returnsSentTrueOnSuccess() {
        EmailAdapter emailAdapter = mock(EmailAdapter.class);
        when(emailAdapter.sendReply(anyString(), anyString(), anyString(), any()))
                .thenReturn(new com.uniserve.adapters.SendResult(true, "uniserve-abc@uniserve.local"));
        EmailAdapterResource resource = newResource(emailAdapter);

        Response response = resource.testSend(
                new EmailAdapterResource.TestSendRequest("citizen@example.com", "Subject", "Body", null));

        assertEquals(200, response.getStatus());
        // Feature 24: the response also carries the Message-ID we put on the
        // mail, so ai-core can stamp it onto the persisted message and route the
        // citizen's reply by it.
        assertEquals(Map.of("sent", true, "channelMessageId", "uniserve-abc@uniserve.local"),
                response.getEntity());
    }

    @Test
    void returnsBadRequestWhenToIsMissing() {
        EmailAdapterResource resource = newResource(mock(EmailAdapter.class));

        Response response = resource.testSend(new EmailAdapterResource.TestSendRequest(null, "s", "b", null));

        assertEquals(400, response.getStatus());
    }

    @Test
    void catchesProviderFailureAndReturnsBadGatewayWithRealMessage() {
        // Regression: previously an exception from emailAdapter.sendReply (e.g.
        // Resend's 403 "you can only send to your own verified address") was
        // left to Quarkus's default handler, which converts ANY uncaught
        // exception into a bare, generic 500 — hiding the real cause from
        // ai-core's caller and forcing a cross-service log hunt.
        EmailAdapter emailAdapter = mock(EmailAdapter.class);
        when(emailAdapter.sendReply(anyString(), anyString(), anyString(), any()))
                .thenThrow(new RuntimeException(
                        "Resend API 403: {\"message\":\"You can only send testing emails to your own email address\"}"));
        EmailAdapterResource resource = newResource(emailAdapter);

        Response response = resource.testSend(
                new EmailAdapterResource.TestSendRequest("citizen@example.com", "Subject", "Body", null));

        assertEquals(502, response.getStatus());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals(Boolean.FALSE, body.get("sent"));
        assertTrue(((String) body.get("error")).contains("Resend API 403"));
    }
}
