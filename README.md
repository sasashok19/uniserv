# UniServe

Multi-tenant AI-powered complaint and feedback portal. See [`docs/ORCHESTRATOR.md`](docs/ORCHESTRATOR.md)
for product vision, phase map, conventions, and feature build order.

> **Status:** Phase 1 scaffold. Services boot and expose health checks only —
> no feature logic yet. Features are implemented in the order defined in the
> orchestrator, starting with `01_EVENT_BUS`.

## Monorepo layout

```
uniserve/
├── services/
│   ├── api-gateway/   # Quarkus (Java 21) — REST API, channel adapters, auth   :8080
│   ├── db-writer/     # Quarkus (Java 21) — sole SQLite WAL writer             :8090
│   └── ai-core/       # Python 3.11 / FastAPI — AI pipeline                    :8001
├── apps/
│   └── dashboard/     # Next.js 14 PWA — agent UI + citizen portal             :3000
├── packages/
│   ├── event-contracts/   # shared JSON event schemas (02f)
│   └── test-stubs/        # .http test files + mock seed scripts
├── infrastructure/
│   ├── docker/        # shared docker assets
│   ├── k8s/           # Kubernetes manifests
│   └── compose/       # docker-compose.dev.yml
└── docs/              # architecture + per-feature specs
```

## Tech stack
Quarkus Java 21 · Python 3.11 FastAPI · Next.js 14 + Tailwind + shadcn/ui ·
SQLite (WAL) · Valkey · Docker · Kubernetes.

## Run the full stack locally (Docker)

```bash
docker compose -f infrastructure/compose/docker-compose.dev.yml up --build
```

Then check health:

| Service     | Health URL                              |
|-------------|-----------------------------------------|
| api-gateway | http://localhost:8080/api/v1/health     |
| db-writer   | http://localhost:8090/api/v1/health     |
| ai-core     | http://localhost:8001/api/v1/health     |
| dashboard   | http://localhost:3000/api/health        |

Quarkus services also expose `/q/health/live` and `/q/health/ready`.
`packages/test-stubs/health.http` hits every endpoint.

## Run a single service for development

```bash
# ai-core
cd services/ai-core && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8001

# dashboard
cd apps/dashboard && npm install && npm run dev

# Quarkus services (needs JDK 21 + Maven; or just use Docker)
cd services/api-gateway && mvn quarkus:dev
cd services/db-writer  && mvn quarkus:dev
```

## Ports
api-gateway `8080` · db-writer `8090` · ai-core `8001` · dashboard `3000` · valkey `6379`

> Note: the feature specs in `docs/` mention `8080`/`8081` for db-writer in a
> couple of places; this scaffold standardises db-writer on **8090** to avoid a
> port clash with api-gateway when both run on the host.
