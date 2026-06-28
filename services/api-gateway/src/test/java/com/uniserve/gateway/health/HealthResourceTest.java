package com.uniserve.gateway.health;

import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.CoreMatchers.is;

@QuarkusTest
class HealthResourceTest {

    @Test
    void healthEndpointReportsUp() {
        given()
                .when().get("/api/v1/health")
                .then()
                .statusCode(200)
                .body("service", is("api-gateway"))
                .body("status", is("UP"));
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
