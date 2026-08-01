package com.uniserve.auth;

import com.uniserve.adapters.email.EmailAdapter;
import com.uniserve.adapters.whatsapp.WhatsAppAdapter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Unit tests for {@link TicketNotifier}'s status-update send (Feature 06 x 14, WhatsApp outbound). */
class TicketNotifierTest {

    private DbWriterClient db;
    private EmailAdapter emailAdapter;
    private WhatsAppAdapter whatsAppAdapter;
    private TicketNotifier notifier;

    @BeforeEach
    void setUp() {
        db = mock(DbWriterClient.class);
        emailAdapter = mock(EmailAdapter.class);
        whatsAppAdapter = mock(WhatsAppAdapter.class);
        notifier = new TicketNotifier();
        notifier.db = db;
        notifier.emailAdapter = emailAdapter;
        notifier.whatsAppAdapter = whatsAppAdapter;
    }

    @Test
    void sendsWhatsAppStatusUpdateForWhatsAppOriginTicket() {
        Map<String, Object> ticket = Map.of(
                "id", "t-1", "channel_origin", "whatsapp", "identity_id", "id-1",
                "ticket_number", "TKT-00099", "origin_message_id", "wamid.orig");
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-1"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("phone", "+919876543210")));

        notifier.sendStatusUpdate(ticket, "resolved", "Fixed the meter fault");

        ArgumentCaptor<String> bodyCaptor = ArgumentCaptor.forClass(String.class);
        verify(whatsAppAdapter).sendReply(eq("+919876543210"), bodyCaptor.capture(), eq("wamid.orig"));
        assertTrue(bodyCaptor.getValue().contains("TKT-00099"));
        assertTrue(bodyCaptor.getValue().contains("resolved"));
        assertTrue(bodyCaptor.getValue().contains("Fixed the meter fault"));
        verifyNoInteractions(emailAdapter);
    }

    @Test
    void skipsWhatsAppSendWhenIdentityHasNoPhone() {
        Map<String, Object> ticket = Map.of(
                "id", "t-2", "channel_origin", "whatsapp", "identity_id", "id-2",
                "ticket_number", "TKT-00100");
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-2"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of()));

        notifier.sendStatusUpdate(ticket, "closed", null);

        verify(whatsAppAdapter, never()).sendReply(anyString(), anyString(), any());
    }

    @Test
    void stillSendsEmailStatusUpdateForEmailOriginTicket() {
        Map<String, Object> ticket = Map.of(
                "id", "t-3", "channel_origin", "email", "identity_id", "id-3",
                "ticket_number", "TKT-00101");
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-3"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("email", "citizen@example.org")));
        when(emailAdapter.sendReply(anyString(), anyString(), anyString(), any())).thenReturn(true);

        notifier.sendStatusUpdate(ticket, "resolved", null);

        verify(emailAdapter).sendReply(eq("citizen@example.org"), anyString(), anyString(), any());
        verifyNoInteractions(whatsAppAdapter);
    }

    @Test
    void doesNothingForChannelsWithoutOutboundSend() {
        Map<String, Object> ticket = Map.of(
                "id", "t-4", "channel_origin", "twitter", "identity_id", "id-4",
                "ticket_number", "TKT-00102");

        notifier.sendStatusUpdate(ticket, "resolved", null);

        verifyNoInteractions(db, emailAdapter, whatsAppAdapter);
    }

    @Test
    void failedWhatsAppSendIsBestEffortAndDoesNotThrow() {
        Map<String, Object> ticket = Map.of(
                "id", "t-5", "channel_origin", "whatsapp", "identity_id", "id-5",
                "ticket_number", "TKT-00103");
        when(db.call(eq("GET"), eq("/api/v1/db/identities/id-5"), any()))
                .thenReturn(new DbWriterClient.ApiResult(200, Map.of("phone", "+919876543211")));
        when(whatsAppAdapter.sendReply(anyString(), anyString(), any()))
                .thenThrow(new RuntimeException("WhatsApp Graph API 500: server error"));

        notifier.sendStatusUpdate(ticket, "resolved", null);
        // no exception propagated — best-effort per the class's contract
    }
}
