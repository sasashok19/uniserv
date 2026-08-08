package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The Unrouted tab end to end through the gateway (Feature 24).
 *
 * The reported bug — an admin clicking "Unrouted" and being shown Jackson's
 * {@code Unexpected character ('<' (code 60))} — is reproduced here at the
 * layer the dashboard actually calls, not just inside {@link DbWriterClient}.
 */
class UnroutedMessagesResourceTest {

    private static final String QUARKUS_404_PAGE =
            "<html><body><h1>Resource not found</h1></body></html>";

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    private UnroutedMessagesResource resourceFor(String role, int status, String body) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, out.length == 0 ? -1 : out.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(out);
            }
        });
        server.start();

        DbWriterClient db = new DbWriterClient();
        db.mapper = new ObjectMapper();
        db.baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        db.internalKey = Optional.empty();

        CurrentUser user = new CurrentUser();
        user.set("a1", "t1", role, "Test User", "test@example.com");

        UnroutedMessagesResource resource = new UnroutedMessagesResource();
        resource.db = db;
        resource.user = user;
        return resource;
    }

    /** RBAC is checked before any call, so an unreachable stub is fine here. */
    private UnroutedMessagesResource resourceFor(String role) throws IOException {
        return resourceFor(role, 200, "{\"data\":[],\"total\":0}");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> bodyOf(Response response) {
        return (Map<String, Object>) response.getEntity();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> errorOf(Response response) {
        return (Map<String, Object>) bodyOf(response).get("error");
    }

    @Test
    void anAdminSeesAnActionableErrorWhenDbWriterHasNoSuchEndpoint() throws IOException {
        // This is the exact reported failure: api-gateway shipped Feature 24,
        // the deployed db-writer had not, and Quarkus answered the unknown path
        // with an HTML page.
        UnroutedMessagesResource resource = resourceFor("admin", 404, QUARKUS_404_PAGE);

        Response response = resource.list(null, null, null);

        assertEquals(404, response.getStatus());
        Map<String, Object> error = errorOf(response);
        assertEquals("DB_WRITER_ENDPOINT_MISSING", error.get("code"));

        String message = String.valueOf(error.get("message"));
        assertTrue(message.contains("GET /api/v1/db/unrouted-messages"), message);
        // The dashboard renders error.message verbatim; parser text must never
        // reach it again.
        assertFalse(message.contains("Unexpected character"), message);
        assertFalse(message.contains("[Source:"), message);
        assertFalse(message.contains("<html"), message);
    }

    @Test
    void theQueueLoadsWhenDbWriterAnswersProperly() throws IOException {
        UnroutedMessagesResource resource = resourceFor("lead", 200,
                "{\"data\":[{\"id\":\"u1\",\"content\":\"ok\",\"status\":\"pending\"}],\"total\":1}");

        Response response = resource.list(null, null, null);

        assertEquals(200, response.getStatus());
        assertEquals(1, bodyOf(response).get("total"));
        assertEquals(1, ((List<?>) bodyOf(response).get("messages")).size());
    }

    @Test
    void aResponseMissingDataStillRendersAsAnEmptyQueue() throws IOException {
        // The panel iterates `messages` and prints `total`; nulls there would
        // read as a broken tab rather than an empty one.
        UnroutedMessagesResource resource = resourceFor("admin", 200, "{}");

        Response response = resource.list(null, null, null);

        assertEquals(200, response.getStatus());
        assertEquals(List.of(), bodyOf(response).get("messages"));
        assertEquals(0, bodyOf(response).get("total"));
    }

    @Test
    void anAgentIsRefusedBeforeAnythingIsQueried() throws IOException {
        // Resolving an entry files a citizen's words onto a ticket of the
        // agent's choosing — not an agent-scoped decision.
        Response response = resourceFor("agent").list(null, null, null);

        assertEquals(403, response.getStatus());
        assertEquals("INSUFFICIENT_ROLE", errorOf(response).get("code"));
    }

    @Test
    void agentsCannotResolveEntriesEither() throws IOException {
        UnroutedMessagesResource resource = resourceFor("agent");

        assertEquals(403, resource.attach("u1", Map.of("ticketNumber", "TKT-00010")).getStatus());
        assertEquals(403, resource.discard("u1").getStatus());
    }

    @Test
    void attachingWithoutATicketReferenceIsRejectedBeforeCallingDbWriter() throws IOException {
        UnroutedMessagesResource resource = resourceFor("admin");

        Response response = resource.attach("u1", Map.of());

        assertEquals(422, response.getStatus());
        assertEquals("TICKET_REQUIRED", errorOf(response).get("code"));
    }

    @Test
    void aTicketNumberThatMatchesNothingIsA404NotACrash() throws IOException {
        // The lead types a ticket NUMBER; the gateway resolves it to an id. An
        // empty result must say so rather than dereferencing nothing.
        UnroutedMessagesResource resource = resourceFor("admin", 200, "{\"data\":[],\"total\":0}");

        Response response = resource.attach("u1", Map.of("ticketNumber", "TKT-99999"));

        assertEquals(404, response.getStatus());
        assertEquals("TICKET_NOT_FOUND", errorOf(response).get("code"));
    }

    @Test
    void theDefaultStatusFilterIsTheWorkNotTheArchive() throws IOException {
        // Defaulting to pending+escalated is what makes the tab a queue; without
        // it a lead would page through every message ever discarded.
        StringBuilder seen = new StringBuilder();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            seen.append(exchange.getRequestURI().getQuery());
            byte[] out = "{\"data\":[],\"total\":0}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, out.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(out);
            }
        });
        server.start();

        DbWriterClient db = new DbWriterClient();
        db.mapper = new ObjectMapper();
        db.baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        db.internalKey = Optional.empty();
        CurrentUser user = new CurrentUser();
        user.set("a1", "t1", "admin", "Test", "t@example.com");
        UnroutedMessagesResource resource = new UnroutedMessagesResource();
        resource.db = db;
        resource.user = user;

        resource.list(null, null, null);

        // getQuery() decodes, so the gateway's %2C reads back as a comma here.
        assertTrue(seen.toString().contains("status=pending,escalated"), seen.toString());
        // Tenant scoping is not optional: this queue holds raw citizen text.
        assertTrue(seen.toString().contains("tenantId=t1"), seen.toString());
    }
}
