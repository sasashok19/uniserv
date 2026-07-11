# ============================================================
# UniServe :: api-gateway (Quarkus, Java 21) — JVM mode image
# ============================================================

# ---- build stage ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -q

# ---- run stage ----
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/target/quarkus-app ./quarkus-app

EXPOSE 8080
ENV QUARKUS_HTTP_HOST=0.0.0.0
USER 1001
CMD ["java", "-jar", "./quarkus-app/quarkus-run.jar"]
