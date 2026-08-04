package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for the WhatsApp outbound Graph API send (Feature 02b outbound). */
class WhatsAppAdapterTest {

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    // ---- payload building (pure) ------------------------------------------

    @Test
    void buildPayloadStripsLeadingPlusAndOmitsContextWhenAbsent() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload("+919876543210", "Hello", null);
        assertEquals("whatsapp", payload.get("messaging_product"));
        assertEquals("919876543210", payload.get("to"));
        assertEquals("text", payload.get("type"));
        assertEquals(Map.of("body", "Hello"), payload.get("text"));
        assertFalse(payload.containsKey("context"));
    }

    @Test
    void buildPayloadIncludesContextMessageIdWhenPresent() {
        Map<String, Object> payload = WhatsAppAdapter.buildPayload("919876543210", "Hi", "wamid.abc123");
        assertEquals(Map.of("message_id", "wamid.abc123"), payload.get("context"));
    }

    @Test
    void stripLeadingPlusHandlesNullAndBareDigits() {
        assertNull(WhatsAppAdapter.stripLeadingPlus(null));
        assertEquals("919876543210", WhatsAppAdapter.stripLeadingPlus("919876543210"));
        assertEquals("919876543210", WhatsAppAdapter.stripLeadingPlus("+919876543210"));
    }

    // ---- config guards ------------------------------------------------------

    @Test
    void sendReplyThrowsWhenAccessTokenMissing() {
        WhatsAppAdapter adapter = newAdapter(Optional.empty(), Optional.of("123456"));
        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> adapter.sendReply("+919876543210", "hi", null));
        assertTrue(ex.getMessage().contains("WHATSAPP_ACCESS_TOKEN"));
    }

    @Test
    void sendReplyThrowsWhenPhoneNumberIdMissing() {
        WhatsAppAdapter adapter = newAdapter(Optional.of("token"), Optional.empty());
        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> adapter.sendReply("+919876543210", "hi", null));
        assertTrue(ex.getMessage().contains("WHATSAPP_PHONE_NUMBER_ID"));
    }

    // ---- actual HTTP call, against a local stub server -----------------------

    @Test
    void sendReplyPostsExpectedRequestAndReturnsTrueOn2xx() throws IOException {
        AtomicReference<String> capturedPath = new AtomicReference<>();
        AtomicReference<String> capturedAuth = new AtomicReference<>();
        AtomicReference<String> capturedBody = new AtomicReference<>();

        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            capturedPath.set(exchange.getRequestURI().getPath());
            capturedAuth.set(exchange.getRequestHeaders().getFirst("Authorization"));
            capturedBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] resp = "{\"messages\":[{\"id\":\"wamid.reply\"}]}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, resp.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(resp);
            }
        });
        server.start();

        WhatsAppAdapter adapter = newAdapter(Optional.of("test-token"), Optional.of("1234567890"));
        adapter.graphApiBaseUrl = "http://127.0.0.1:" + server.getAddress().getPort();

        com.uniserve.adapters.SendResult result =
                adapter.sendReply("+919876543210", "Your ticket is resolved", "wamid.orig001");

        assertTrue(result.sent());
        assertEquals("/v21.0/1234567890/messages", capturedPath.get());
        assertEquals("Bearer test-token", capturedAuth.get());
        assertTrue(capturedBody.get().contains("\"to\":\"919876543210\""));
        assertTrue(capturedBody.get().contains("\"message_id\":\"wamid.orig001\""));
    }

    @Test
    void sendReplyThrowsOnGraphApiError() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            byte[] resp = "{\"error\":{\"message\":\"Invalid parameter\"}}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(400, resp.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(resp);
            }
        });
        server.start();

        WhatsAppAdapter adapter = newAdapter(Optional.of("test-token"), Optional.of("1234567890"));
        adapter.graphApiBaseUrl = "http://127.0.0.1:" + server.getAddress().getPort();

        RuntimeException ex = assertThrows(RuntimeException.class,
                () -> adapter.sendReply("+919876543210", "hi", null));
        assertTrue(ex.getMessage().contains("400"));
        assertTrue(ex.getMessage().contains("Invalid parameter"));
    }

    private static WhatsAppAdapter newAdapter(Optional<String> token, Optional<String> phoneNumberId) {
        WhatsAppAdapter adapter = new WhatsAppAdapter();
        adapter.mapper = new ObjectMapper();
        adapter.accessToken = token;
        adapter.phoneNumberId = phoneNumberId;
        adapter.graphApiBaseUrl = "https://graph.facebook.com";
        adapter.apiVersion = "v21.0";
        return adapter;
    }
}
