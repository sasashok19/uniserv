package com.uniserve.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * HTTP client from api-gateway to the db-writer data API (Feature 11). Used for
 * agent lookup/CRUD, tenant config and ticket queries during auth/RBAC handling.
 */
@ApplicationScoped
public class DbWriterClient {

    private static final Logger LOG = Logger.getLogger(DbWriterClient.class);

    @Inject
    ObjectMapper mapper;

    @ConfigProperty(name = "gateway.db-writer.url", defaultValue = "http://localhost:8090")
    String baseUrl;

    @ConfigProperty(name = "db-writer.internal-api-key")
    Optional<String> internalKey;

    /**
     * 5 seconds was not enough. db-writer runs on a platform that suspends an
     * idle instance, and waking one routinely takes longer than that — so the
     * hourly {@link TicketAutoCloseScheduler} tick, which is the one call
     * guaranteed to arrive after a long idle period, failed against a cold
     * instance every time. Observed in production as a recurring
     * {@code auto-close-unconfirmed call failed: status=502 ... HTTP connect
     * timed out}, which meant unconfirmed tickets were never swept.
     */
    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(20);

    /**
     * Retries are limited to failures that happened while CONNECTING. That
     * distinction is the whole safety argument: a connect failure means the
     * request never reached db-writer, so replaying it cannot double-apply a
     * POST. A read timeout gets no retry — the write may well have landed.
     */
    private static final int CONNECT_RETRIES = 2;
    private static final Duration RETRY_BACKOFF = Duration.ofSeconds(2);

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(CONNECT_TIMEOUT).build();

    /** True when the request never reached the server, so replaying it is safe. */
    private static boolean isConnectFailure(Exception e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof java.net.http.HttpConnectTimeoutException
                    || t instanceof java.net.ConnectException) {
                return true;
            }
        }
        return false;
    }

    public Optional<Map<String, Object>> findAgentByEmail(String email) {
        List<Map<String, Object>> data = dataList("/api/v1/db/agents?email=" + enc(email));
        return data.isEmpty() ? Optional.empty() : Optional.of(data.get(0));
    }

    public Optional<Map<String, Object>> getAgentById(String id) {
        try {
            return Optional.of(send("GET", "/api/v1/db/agents/" + id, null));
        } catch (DbWriterException e) {
            if (e.status == 404) {
                return Optional.empty();
            }
            throw e;
        }
    }

    public List<Map<String, Object>> listAgents(String tenantId) {
        return dataList("/api/v1/db/agents?tenantId=" + enc(tenantId));
    }

    public Map<String, Object> createAgent(Map<String, Object> payload) {
        return send("POST", "/api/v1/db/agents", payload);
    }

    public Map<String, Object> updateAgent(String id, Map<String, Object> payload) {
        return send("PATCH", "/api/v1/db/agents/" + id, payload);
    }

    public List<Map<String, Object>> listTickets(String query) {
        return dataList("/api/v1/db/tickets?" + query);
    }

    public Optional<Map<String, Object>> findIdentityByAnonRef(String ref) {
        List<Map<String, Object>> data = dataList("/api/v1/db/identities?anonRefId=" + enc(ref));
        return data.isEmpty() ? Optional.empty() : Optional.of(data.get(0));
    }

    public Optional<Map<String, Object>> findIdentityByEmail(String tenantId, String email) {
        List<Map<String, Object>> data = dataList(
                "/api/v1/db/identities?tenantId=" + enc(tenantId) + "&email=" + enc(email));
        return data.isEmpty() ? Optional.empty() : Optional.of(data.get(0));
    }

    public List<Map<String, Object>> ticketNotes(String id) {
        return dataList("/api/v1/db/tickets/" + id + "/notes");
    }

    /** Pass-through call that does NOT throw on 4xx/5xx (for transition 422, summary 503). */
    public ApiResult call(String method, String path, Object body) {
        Exception last = null;
        for (int attempt = 0; attempt <= CONNECT_RETRIES; attempt++) {
            try {
                HttpRequest.Builder b = HttpRequest.newBuilder()
                        .uri(URI.create(baseUrl + path))
                        .timeout(Duration.ofSeconds(10))
                        .header("Content-Type", "application/json");
                if (internalKey.isPresent() && !internalKey.get().isBlank()) {
                    b.header("X-Internal-Key", internalKey.get());
                }
                HttpRequest.BodyPublisher publisher = body == null
                        ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body));
                b.method(method, publisher);
                HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
                // Parsing happens inside toResult, NOT here: a parse failure is
                // not a transport failure, and letting it fall into the catch
                // below is exactly what leaked Jackson's parser message to the
                // dashboard. See toResult.
                return toResult(resp.statusCode(), resp.body(), method, path);
            } catch (Exception e) {
                last = e;
                if (attempt == CONNECT_RETRIES || !isConnectFailure(e)) {
                    break;
                }
                // Waking a suspended instance takes a moment; give it one.
                try {
                    Thread.sleep(RETRY_BACKOFF.toMillis());
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        // String.valueOf, not the raw message: Map.of() throws NPE on a null
        // value, and several transport exceptions (ConnectException among
        // them) carry no message — so the failure handler itself used to
        // throw, turning a recoverable 502 into an NPE at the call site.
        return new ApiResult(502, Map.of("error",
                Map.of("code", "DB_WRITER_UNAVAILABLE",
                        "message", String.valueOf(last == null ? "unknown" : last.getMessage()))));
    }

    public record ApiResult(int status, Map<String, Object> body) {
    }

    public Map<String, Object> getTenant(String id) {
        return send("GET", "/api/v1/db/tenants/" + id, null);
    }

    public Map<String, Object> updateTenantConfig(String id, String configJson) {
        return send("PUT", "/api/v1/db/tenants/" + id + "/config", Map.of("configJson", configJson));
    }

    // ---- internals -------------------------------------------------------

    /**
     * Turn an upstream response into an {@link ApiResult} without ever letting a
     * JSON parse failure escape as Jackson's own words.
     *
     * <p>db-writer does not always answer in JSON. An unmatched path gets
     * Quarkus's built-in {@code <html><body><h1>Resource not found</h1></body></html>},
     * and the platforms in front of it (Railway, Render) serve their own HTML
     * pages while an instance is down or still waking. Feeding either to
     * {@code mapper.readValue} throws, and the old code let that land in the
     * transport handler below — so {@code error.message} became the parser's
     * own text, <em>"Unexpected character ('&lt;' (code 60)): expected a valid
     * value ... at [Source: REDACTED ...]"</em>, and the dashboard showed that
     * to the admin verbatim.
     *
     * <p>That is the reported "Unrouted" tab failure: api-gateway shipped
     * Feature 24, the deployed db-writer had not, so
     * {@code /api/v1/db/unrouted-messages} 404'd with an HTML page. The
     * deployment is the root cause, but the parser message was pure noise —
     * it named neither the endpoint nor the status that would point at it.
     *
     * <p>The upstream status is preserved on a failure so the caller can still
     * surface a 404 as a 404. A NON-failure status with an unparseable body is
     * downgraded to 502: a "200 OK" the gateway cannot read is not a success,
     * and passing it through would hand callers an empty map that looks like a
     * legitimately empty result.
     */
    private ApiResult toResult(int status, String raw, String method, String path) {
        if (raw == null || raw.isBlank()) {
            return new ApiResult(status, Map.of());
        }
        try {
            return new ApiResult(status, mapper.readValue(raw, new TypeReference<Map<String, Object>>() {
            }));
        } catch (Exception parseFailure) {
            LOG.errorf("db-writer %s %s -> HTTP %d with a body that is not JSON: %s",
                    method, path, status, snippet(raw));
            return new ApiResult(status >= 400 ? status : 502,
                    Map.of("error", nonJsonError(status, method, path)));
        }
    }

    /**
     * A message an admin can act on. A 404 here is almost always version drift —
     * the gateway calling an endpoint the deployed db-writer does not have yet —
     * so it says so rather than making someone read a stack trace.
     */
    private static Map<String, Object> nonJsonError(int status, String method, String path) {
        String endpoint = method + " " + path.split("\\?")[0];
        if (status == 404) {
            return Map.of("code", "DB_WRITER_ENDPOINT_MISSING",
                    "message", "The data service does not have " + endpoint + " (HTTP 404). "
                            + "db-writer is most likely running an older build than api-gateway — "
                            + "redeploy db-writer from the current main branch.");
        }
        return Map.of("code", "DB_WRITER_BAD_RESPONSE",
                "message", "The data service answered " + endpoint + " with HTTP " + status
                        + " and a body that is not JSON (an error page, not data). "
                        + "It is most likely down, restarting, or still waking.");
    }

    /** Bounded and single-line: an HTML error page must not flood the log. */
    private static String snippet(String raw) {
        String flat = raw.replaceAll("\\s+", " ").trim();
        return flat.length() <= 200 ? flat : flat.substring(0, 200) + "…";
    }

    private List<Map<String, Object>> dataList(String path) {
        Map<String, Object> body = send("GET", path, null);
        Object data = body.get("data");
        if (data == null) {
            return List.of();
        }
        return mapper.convertValue(data, new TypeReference<>() {
        });
    }

    private Map<String, Object> send(String method, String path, Object body) {
        try {
            HttpRequest.Builder b = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + path))
                    .timeout(Duration.ofSeconds(10))
                    .header("Content-Type", "application/json");
            if (internalKey.isPresent() && !internalKey.get().isBlank()) {
                b.header("X-Internal-Key", internalKey.get());
            }
            HttpRequest.BodyPublisher publisher = body == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body));
            b.method(method, publisher);

            HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new DbWriterException(resp.statusCode(),
                        "db-writer " + method + " " + path + " -> " + resp.statusCode()
                                + ": " + snippet(String.valueOf(resp.body())));
            }
            // Routed through toResult for the same reason as call(): a body that
            // is not JSON must surface as a named failure, never as Jackson's
            // "Unexpected character ('<' (code 60))" handed to a caller.
            ApiResult parsed = toResult(resp.statusCode(), resp.body(), method, path);
            if (parsed.status() >= 400) {
                throw new DbWriterException(parsed.status(),
                        "db-writer " + method + " " + path + " returned a non-JSON body");
            }
            return parsed.body();
        } catch (DbWriterException e) {
            throw e;
        } catch (Exception e) {
            throw new DbWriterException(502, "db-writer call failed: " + e.getMessage());
        }
    }

    private static String enc(String v) {
        return URLEncoder.encode(v, StandardCharsets.UTF_8);
    }

    /** Carries the upstream status so callers can surface it. */
    public static class DbWriterException extends RuntimeException {
        public final int status;

        public DbWriterException(int status, String message) {
            super(message);
            this.status = status;
        }
    }
}
