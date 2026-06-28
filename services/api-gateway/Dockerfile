# ============================================================
# UniServe :: api-gateway (Quarkus, Java 21) — JVM mode image
# ============================================================

# ---- build stage ----
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
# Warm the dependency cache so source-only changes don't re-resolve everything.
RUN mvn -B -q dependency:go-offline || true
COPY src ./src
RUN mvn -B clean package -DskipTests

# ---- run stage ----
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /app/target/quarkus-app/lib/ ./lib/
COPY --from=build /app/target/quarkus-app/*.jar ./
COPY --from=build /app/target/quarkus-app/app/ ./app/
COPY --from=build /app/target/quarkus-app/quarkus/ ./quarkus/

EXPOSE 8080
ENV QUARKUS_HTTP_HOST=0.0.0.0
ENTRYPOINT ["java", "-jar", "quarkus-run.jar"]
