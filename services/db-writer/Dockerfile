# ============================================================
# UniServe :: db-writer (Quarkus, Java 21) — JVM mode image
# ============================================================

# ---- build stage ----
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn -B -q dependency:go-offline || true
COPY src ./src
RUN mvn -B clean package -DskipTests

# ---- run stage ----
FROM eclipse-temurin:21-jre
WORKDIR /app
# Persistent location for the SQLite WAL database (mount a volume here).
RUN mkdir -p /data
COPY --from=build /app/target/quarkus-app/lib/ ./lib/
COPY --from=build /app/target/quarkus-app/*.jar ./
COPY --from=build /app/target/quarkus-app/app/ ./app/
COPY --from=build /app/target/quarkus-app/quarkus/ ./quarkus/

EXPOSE 8090
ENV QUARKUS_HTTP_HOST=0.0.0.0
ENV DB_WRITER_DB_PATH=/data/uniserve.db
ENTRYPOINT ["java", "-jar", "quarkus-run.jar"]
