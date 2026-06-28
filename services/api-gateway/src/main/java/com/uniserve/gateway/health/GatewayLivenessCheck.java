package com.uniserve.gateway.health;

import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.health.HealthCheck;
import org.eclipse.microprofile.health.HealthCheckResponse;
import org.eclipse.microprofile.health.Liveness;

/**
 * Liveness probe for api-gateway, exposed at /q/health/live.
 * Phase 1 scaffold: reports UP once the application context is running.
 */
@Liveness
@ApplicationScoped
public class GatewayLivenessCheck implements HealthCheck {

    @Override
    public HealthCheckResponse call() {
        return HealthCheckResponse.named("api-gateway").up().build();
    }
}
