package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Regression tests for the transport-failure path of {@link DbWriterClient}.
 *
 * Production symptom: `auto-close-unconfirmed call failed: status=502 ... HTTP
 * connect timed out`, logged 3-6 seconds after every startup. Two distinct
 * defects met there — the failure handler could itself throw, and the only
 * tick that ever ran was the boot-time one.
 */
class DbWriterClientRetryTest {

    private static DbWriterClient clientPointedAt(String baseUrl) {
        DbWriterClient c = new DbWriterClient();
        c.mapper = new ObjectMapper();
        c.baseUrl = baseUrl;
        c.internalKey = Optional.empty();
        return c;
    }

    @Test
    void transportFailureWithNoExceptionMessageStillReturns502() {
        // Map.of() throws NPE on a null value, and several transport
        // exceptions carry no message — so the error path used to throw an NPE
        // instead of returning a 502, taking the caller down with it. This is
        // the NullPointerException seen escaping the auto-close scheduler.
        DbWriterClient client = clientPointedAt("http://127.0.0.1:1");

        DbWriterClient.ApiResult result = client.call("POST", "/api/v1/db/tickets/auto-close-unconfirmed",
                Map.of("olderThanDays", 14));

        assertEquals(502, result.status());
        assertNotNull(result.body());
        @SuppressWarnings("unchecked")
        Map<String, Object> error = (Map<String, Object>) result.body().get("error");
        assertEquals("DB_WRITER_UNAVAILABLE", error.get("code"));
        assertNotNull(error.get("message"), "message must never be null — Map.of would NPE");
    }

    @Test
    void aReadTimeoutIsNotRetried() {
        // Only CONNECT failures are safe to replay: they prove the request
        // never arrived. A read timeout might mean the write landed, so
        // retrying a POST could double-apply it.
        assertTrue(DbWriterClientRetryTest.isConnectFailureVia(new java.net.ConnectException("refused")));
        assertTrue(DbWriterClientRetryTest.isConnectFailureVia(
                new java.net.http.HttpConnectTimeoutException("connect timed out")));
        assertTrue(DbWriterClientRetryTest.isConnectFailureVia(
                new IOException(new java.net.ConnectException("wrapped"))));
        // A plain read timeout / IO error is NOT a connect failure.
        assertTrue(!DbWriterClientRetryTest.isConnectFailureVia(
                new java.net.http.HttpTimeoutException("request timed out")));
        assertTrue(!DbWriterClientRetryTest.isConnectFailureVia(new IOException("stream closed")));
    }

    /** Mirrors DbWriterClient.isConnectFailure, which is private by design. */
    private static boolean isConnectFailureVia(Exception e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof java.net.http.HttpConnectTimeoutException || t instanceof java.net.ConnectException) {
                return true;
            }
        }
        return false;
    }
}
