package com.uniserve.auth;

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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Regression tests for the reported "Unrouted" tab failure.
 *
 * <p>Symptom, seen by an admin who clicked the tab:
 * <pre>
 * Unexpected character ('&lt;' (code 60)): expected a valid value (JSON String,
 * Number, Array, Object or token 'null', 'true' or 'false')
 * at [Source: REDACTED ...]; line: 1, column: 1
 * </pre>
 *
 * <p>Jackson's own parser message, shown to a user. It arose because the
 * deployed db-writer had no {@code /api/v1/db/unrouted-messages} route (the
 * gateway shipped Feature 24 ahead of it), so Quarkus answered with its HTML
 * 404 page — {@code <html><body><h1>Resource not found</h1></body></html>} —
 * and {@link DbWriterClient} parsed that in the same try block that handles
 * transport faults. The version drift is a deployment matter; this test pins
 * the code half: a non-JSON upstream body must become a NAMED error that says
 * which endpoint and which status, and must never leak parser text.
 */
class DbWriterNonJsonResponseTest {

    /** Byte-for-byte what the live Railway db-writer returns for an unknown path. */
    private static final String QUARKUS_404_PAGE =
            "<html><body><h1>Resource not found</h1></body></html>";

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    /** A db-writer stand-in that answers every request with one canned response. */
    private DbWriterClient clientServing(int status, String contentType, String body) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", contentType);
            exchange.sendResponseHeaders(status, out.length == 0 ? -1 : out.length);
            if (out.length > 0) {
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(out);
                }
            }
        });
        server.start();

        DbWriterClient c = new DbWriterClient();
        c.mapper = new ObjectMapper();
        c.baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        c.internalKey = Optional.empty();
        return c;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> errorOf(DbWriterClient.ApiResult result) {
        return (Map<String, Object>) result.body().get("error");
    }

    @Test
    void anHtml404BecomesANamedErrorInsteadOfAJacksonParserMessage() throws IOException {
        DbWriterClient client = clientServing(404, "text/html; charset=utf-8", QUARKUS_404_PAGE);

        DbWriterClient.ApiResult result = client.call(
                "GET", "/api/v1/db/unrouted-messages?tenantId=t1&status=pending,escalated", null);

        // The upstream status survives: a missing endpoint must not be reported
        // as a generic 502, or nobody can tell version drift from an outage.
        assertEquals(404, result.status());
        Map<String, Object> error = errorOf(result);
        assertEquals("DB_WRITER_ENDPOINT_MISSING", error.get("code"));

        String message = String.valueOf(error.get("message"));
        // The whole point: this is what the admin now reads instead of parser noise.
        assertTrue(message.contains("GET /api/v1/db/unrouted-messages"),
                "message must name the endpoint that is missing, got: " + message);
        assertTrue(message.contains("redeploy db-writer"),
                "message must say what to actually do about it, got: " + message);
        // The query string carries a tenant id; it belongs in logs, not in the UI.
        assertFalse(message.contains("tenantId"), "message must not echo the query string");
        assertNoParserNoise(message);
    }

    @Test
    void aPlatformErrorPageBecomesANamedErrorAndKeepsItsStatus() throws IOException {
        // Railway/Render serve their own HTML when an instance is down or waking.
        DbWriterClient client = clientServing(503, "text/html",
                "<!DOCTYPE html><html><head><title>Application failed to respond</title></head>"
                        + "<body><h1>502</h1></body></html>");

        DbWriterClient.ApiResult result = client.call("GET", "/api/v1/db/tickets?tenantId=t1", null);

        assertEquals(503, result.status());
        Map<String, Object> error = errorOf(result);
        assertEquals("DB_WRITER_BAD_RESPONSE", error.get("code"));
        assertNoParserNoise(String.valueOf(error.get("message")));
    }

    @Test
    void anUnreadableSuccessIsDowngradedTo502RatherThanPassedOffAsData() throws IOException {
        // A "200 OK" the gateway cannot parse is not a success. Passing the
        // status through would hand callers an empty map, which reads exactly
        // like a legitimately empty result — the Unrouted tab would have shown
        // "Nothing unrouted" while the queue was in fact unreadable.
        DbWriterClient client = clientServing(200, "text/html", "<html><body>hello</body></html>");

        DbWriterClient.ApiResult result = client.call("GET", "/api/v1/db/unrouted-messages?tenantId=t1", null);

        assertEquals(502, result.status());
        assertEquals("DB_WRITER_BAD_RESPONSE", errorOf(result).get("code"));
    }

    @Test
    void aJsonArrayIsAlsoTreatedAsUnreadableRatherThanThrowing() throws IOException {
        // Valid JSON, wrong shape: readValue into a Map throws just as loudly.
        DbWriterClient client = clientServing(200, "application/json", "[1,2,3]");

        DbWriterClient.ApiResult result = client.call("GET", "/api/v1/db/unrouted-messages", null);

        assertEquals(502, result.status());
        assertEquals("DB_WRITER_BAD_RESPONSE", errorOf(result).get("code"));
    }

    @Test
    void ordinaryJsonStillParsesUnchanged() throws IOException {
        DbWriterClient client = clientServing(200, "application/json",
                "{\"data\":[{\"id\":\"u1\",\"content\":\"ok\"}],\"total\":1}");

        DbWriterClient.ApiResult result = client.call("GET", "/api/v1/db/unrouted-messages", null);

        assertEquals(200, result.status());
        assertEquals(1, result.body().get("total"));
        assertTrue(result.body().get("data") instanceof java.util.List);
    }

    @Test
    void aJsonErrorFromDbWriterIsPassedThroughUntouched() throws IOException {
        // The InternalKeyFilter's 401 is already JSON and already useful — the
        // new handling must not overwrite a perfectly good upstream error.
        DbWriterClient client = clientServing(401, "application/json",
                "{\"error\":{\"code\":\"UNAUTHORIZED\",\"message\":\"Valid X-Internal-Key required\"}}");

        DbWriterClient.ApiResult result = client.call("GET", "/api/v1/db/unrouted-messages", null);

        assertEquals(401, result.status());
        assertEquals("UNAUTHORIZED", errorOf(result).get("code"));
    }

    @Test
    void anEmptyBodyIsStillAnEmptyMap() throws IOException {
        DbWriterClient client = clientServing(204, "application/json", "");

        DbWriterClient.ApiResult result = client.call("POST", "/api/v1/db/unrouted-messages/x/discard", null);

        assertEquals(204, result.status());
        assertTrue(result.body().isEmpty());
    }

    @Test
    void theThrowingVariantAlsoRefusesToCarryParserText() throws IOException {
        // send() is the other half of the client (agent lookup, tenant config,
        // ticket queries). It had the same naked readValue.
        DbWriterClient client = clientServing(200, "text/html", QUARKUS_404_PAGE);

        DbWriterClient.DbWriterException thrown = org.junit.jupiter.api.Assertions.assertThrows(
                DbWriterClient.DbWriterException.class,
                () -> client.listTickets("tenantId=t1"));

        assertNoParserNoise(String.valueOf(thrown.getMessage()));
    }

    @Test
    void theThrowingVariantDoesNotPasteAnEntireErrorPageIntoItsMessage() throws IOException {
        DbWriterClient client = clientServing(500, "text/html",
                "<html><body>" + "x".repeat(5000) + "</body></html>");

        DbWriterClient.DbWriterException thrown = org.junit.jupiter.api.Assertions.assertThrows(
                DbWriterClient.DbWriterException.class,
                () -> client.listTickets("tenantId=t1"));

        assertEquals(500, thrown.status);
        assertTrue(thrown.getMessage().length() < 500,
                "an HTML error page must be truncated, not pasted whole into a log line");
    }

    /** The exact shape of the message the admin saw. None of it may survive. */
    private static void assertNoParserNoise(String message) {
        assertFalse(message.contains("Unexpected character"), "leaked Jackson parser text: " + message);
        assertFalse(message.contains("code 60"), "leaked Jackson parser text: " + message);
        assertFalse(message.contains("[Source:"), "leaked Jackson parser text: " + message);
        assertFalse(message.contains("<html"), "leaked raw HTML: " + message);
    }
}
