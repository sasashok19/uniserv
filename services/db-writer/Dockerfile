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
# Persistent location for the SQLite WAL database (mount a volume here); owned by the
# non-root runtime user so it stays writable after USER 1001 below.
RUN mkdir -p /data && chown -R 1001:1001 /data
COPY --from=build /app/target/quarkus-app ./quarkus-app

EXPOSE 8090
ENV QUARKUS_HTTP_HOST=0.0.0.0
ENV DB_WRITER_DB_PATH=/data/uniserve.db
USER 1001
CMD ["java", "-jar", "./quarkus-app/quarkus-run.jar"]
