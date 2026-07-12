package com.uniserve.dbwriter.security;

import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.container.ContainerResponseContext;
import jakarta.ws.rs.container.ContainerResponseFilter;
import jakarta.ws.rs.ext.Provider;
import org.jboss.logging.Logger;

/**
 * Logs every {@code /api/v1/db/*} request (Feature 04 observability):
 * method, path, status, and duration. Also surfaces {@code X-Trace-Id} when
 * the caller supplied one, so a request here can be correlated back to the
 * originating channel message (see ai-core's {@code DbWriterClient} and
 * api-gateway's adapter logging) — the same trace id threads through
 * scripts/combined.log across all three services for one transaction.
 *
 * <p>INFO for 2xx/3xx, WARN for 4xx, ERROR for 5xx — matches {@code
 * quarkus.log.level}'s dev default of INFO ("log everything") vs. a
 * production override of ERROR.
 */
@Provider
public class RequestLoggingFilter implements ContainerRequestFilter, ContainerResponseFilter {

    private static final Logger LOG = Logger.getLogger(RequestLoggingFilter.class);
    private static final String START_PROPERTY = "requestStartNanos";

    @Override
    public void filter(ContainerRequestContext requestContext) {
        requestContext.setProperty(START_PROPERTY, System.nanoTime());
    }

    @Override
    public void filter(ContainerRequestContext requestContext, ContainerResponseContext responseContext) {
        String path = requestContext.getUriInfo().getPath();
        if (path == null || !path.contains("api/v1/db/")) {
            return; // only the data API — health/schema/etc. stay quiet
        }
        String traceId = requestContext.getHeaderString("X-Trace-Id");
        String method = requestContext.getMethod();
        int status = responseContext.getStatus();
        long durationMs = durationMs(requestContext);
        if (status >= 500) {
            LOG.errorf("db-writer request failed: traceId=%s %s /%s status=%d durationMs=%d",
                    traceId, method, path, status, durationMs);
        } else if (status >= 400) {
            LOG.warnf("db-writer request rejected: traceId=%s %s /%s status=%d durationMs=%d",
                    traceId, method, path, status, durationMs);
        } else {
            LOG.infof("db-writer request: traceId=%s %s /%s status=%d durationMs=%d",
                    traceId, method, path, status, durationMs);
        }
    }

    private long durationMs(ContainerRequestContext requestContext) {
        Object start = requestContext.getProperty(START_PROPERTY);
        if (start instanceof Long startNanos) {
            return (System.nanoTime() - startNanos) / 1_000_000;
        }
        return -1;
    }
}
