package com.uniserve.gateway.health;

import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.CoreMatchers.is;
import static org.hamcrest.CoreMatchers.notNullValue;

@QuarkusTest
class HealthResourceTest {

    @Test
    void healthEndpointReportsAggregate() {
        // Feature 16: aggregate health. api-gateway (self) is always healthy;
        // downstream services may be unavailable in an isolated @QuarkusTest.
        given()
                .when().get("/api/v1/health")
                .then()
                .statusCode(200)
                .body("services.apiGateway", is("healthy"))
                .body("status", is(notNullValue()));
    }

    @Test
    void livenessProbeReportsUp() {
        given()
                .when().get("/q/health/live")
                .then()
                .statusCode(200)
                .body("status", is("UP"));
    }
}
