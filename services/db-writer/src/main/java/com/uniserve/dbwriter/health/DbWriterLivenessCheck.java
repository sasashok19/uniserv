package com.uniserve.dbwriter.health;

import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.health.HealthCheck;
import org.eclipse.microprofile.health.HealthCheckResponse;
import org.eclipse.microprofile.health.Liveness;

/**
 * Liveness probe for db-writer, exposed at /q/health/live.
 * Phase 1 scaffold: reports UP once the application context is running.
 * (Datasource readiness is reported separately at /q/health/ready.)
 */
@Liveness
@ApplicationScoped
public class DbWriterLivenessCheck implements HealthCheck {

    @Override
    public HealthCheckResponse call() {
        return HealthCheckResponse.named("db-writer").up().build();
    }
}
