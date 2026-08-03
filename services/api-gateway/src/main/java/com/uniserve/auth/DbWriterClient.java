package com.uniserve.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

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
                Map<String, Object> parsed = (resp.body() == null || resp.body().isBlank())
                        ? Map.of()
                        : mapper.readValue(resp.body(), new TypeReference<>() {
                        });
                return new ApiResult(resp.statusCode(), parsed);
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
                        "db-writer " + method + " " + path + " -> " + resp.statusCode() + ": " + resp.body());
            }
            if (resp.body() == null || resp.body().isBlank()) {
                return Map.of();
            }
            return mapper.readValue(resp.body(), new TypeReference<>() {
            });
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
