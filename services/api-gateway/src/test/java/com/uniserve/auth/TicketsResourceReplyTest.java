package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import com.uniserve.adapters.whatsapp.WhatsAppAdapter;
import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Unit tests for {@link TicketsResource#reply}'s WhatsApp outbound branch (Feature 12/14). */
class TicketsResourceReplyTest {

    private DbWriterClient db;
    private WhatsAppAdapter whatsAppAdapter;
    private EmailAdapter emailAdapter;
    private TicketsResource resource;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        db = mock(DbWriterClient.class);
        emailAdapter = mock(EmailAdapter.class);
        whatsAppAdapter = mock(WhatsAppAdapter.class);

        CurrentUser user = mock(CurrentUser.class);
        when(user.agentId()).thenReturn("agent-1");

        resource = new TicketsResource();
        resource.db = db;
        resource.emailAdapter = emailAdapter;
        resource.whatsAppAdapter = whatsAppAdapter;
        resource.user = user;
        resource.notifier = mock(TicketNotifier.class);

        Map<String, Object> ticket = Map.of(
                "id", "tkt-1", "channel_origin", "whatsapp", "identity_id", "id-9",
                "ticket_number", "TKT-00200", "origin_message_id", "wamid.orig9");
        when(db.call(eq("GET"), eq("/api/v1/db/tickets/tkt-1"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, ticket));
        when(db.call(eq("POST"), eq("/api/v1/db/tickets/tkt-1/messages"), any()))
                .thenReturn(new DbWriterClient.ApiResult(201, Map.of()));
    }

    @Test
    void sendsWhatsAppReplyAndReportsSentTrue() {
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-9"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("phone", "+919876543212")));
        when(whatsAppAdapter.sendReply(eq("+919876543212"), eq("Please visit the office tomorrow"), eq("wamid.orig9")))
                .thenReturn(new com.uniserve.adapters.SendResult(true, "prov-1"));

        Response response = resource.reply("tkt-1", Map.of("content", "Please visit the office tomorrow"));

        assertEquals(200, response.getStatus());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals("whatsapp", body.get("channel"));
        assertEquals(Boolean.TRUE, body.get("sent"));
        assertTrue(!body.containsKey("sendError"));
    }

    @Test
    void reportsSendErrorWhenIdentityHasNoPhone() {
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-9"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of()));

        Response response = resource.reply("tkt-1", Map.of("content", "Update"));

        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals(Boolean.FALSE, body.get("sent"));
        assertEquals("No phone number on file for this ticket's identity", body.get("sendError"));
        verify(whatsAppAdapter, never()).sendReply(anyString(), anyString(), any());
    }

    @Test
    void reportsSendErrorWhenGraphApiCallThrows() {
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-9"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("phone", "+919876543212")));
        when(whatsAppAdapter.sendReply(anyString(), anyString(), any()))
                .thenThrow(new RuntimeException("WhatsApp Graph API 401: invalid token"));

        Response response = resource.reply("tkt-1", Map.of("content", "Update"));

        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getEntity();
        assertEquals(Boolean.FALSE, body.get("sent"));
        assertEquals("WhatsApp Graph API 401: invalid token", body.get("sendError"));
    }
}
