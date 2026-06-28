# docker

Per-service Dockerfiles live **next to each service** (idiomatic for Quarkus,
FastAPI, and Next.js builds, and what `docker-compose.dev.yml` references):

- `services/api-gateway/Dockerfile`
- `services/db-writer/Dockerfile`
- `services/ai-core/Dockerfile`
- `apps/dashboard/Dockerfile`

This folder holds shared/base Docker assets that are introduced later
(e.g. a common JRE base image or the db-writer backup sidecar in 16_DEPLOYMENT).
