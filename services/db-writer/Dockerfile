# ============================================================
# UniServe :: db-writer (Quarkus, Java 21) — JVM mode image
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
# Persistent location for the SQLite WAL database (mount a volume here).
# Runs as root: a platform-mounted volume (e.g. Railway) arrives with its own
# ownership at container start, overriding any chown baked into the image
# layer here, so a non-root user can end up unable to write to it.
RUN mkdir -p /data
COPY --from=build /app/target/quarkus-app ./quarkus-app

EXPOSE 8090
ENV QUARKUS_HTTP_HOST=0.0.0.0
ENV DB_WRITER_DB_PATH=/data/uniserve.db
CMD ["java", "-jar", "./quarkus-app/quarkus-run.jar"]
