# System Overview — Architecture Reference

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                            │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ api-gateway  │  │  ai-core     │  │   dashboard          │  │
│  │ (Quarkus)    │  │  (Python)    │  │   (Next.js)          │  │
│  │ N replicas   │  │  N replicas  │  │   N replicas         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘  │
│         │                 │                                      │
│         └────────┬────────┘                                      │
│                  │                                               │
│          ┌───────▼────────┐                                      │
│          │   Valkey        │  ← event bus                        │
│          └───────┬────────┘                                      │
│                  │                                               │
│          ┌───────▼────────┐                                      │
│          │  db-writer     │  ← single pod, sole DB writer        │
│          │  (Quarkus)     │                                      │
│          └───────┬────────┘                                      │
│                  │                                               │
│          ┌───────▼────────┐                                      │
│          │  SQLite WAL    │  ← Persistent Volume Claim           │
│          └────────────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
```

## Service Responsibilities

### api-gateway (Quarkus)
- Receives inbound channel messages (Email IMAP, WhatsApp webhook)
- Authenticates and authorises all API requests (JWT)
- Routes events to Valkey
- Exposes REST APIs consumed by the dashboard BFF
- PHASE_2: Twitter, IVR, Web Chat adapters added here

### ai-core (Python FastAPI)
- Consumes events from Valkey
- Runs identity gate decision tree
- Calls LLM via LLM gateway (OpenAI / Anthropic / Gemini / Ollama)
- PII scrubber wraps all LLM calls
- Classification, deduplication, priority scoring
- Publishes results back to Valkey

### db-writer (Quarkus)
- ONLY service that writes to SQLite
- Exposes REST API for all reads and writes
- Caffeine in-memory read cache (short TTL)
- Backup sidecar copies SQLite file to cloud storage on schedule
- PHASE_2: PiiEncryptionService added here

### dashboard (Next.js)
- Agent dashboard: three tabs (Analytics, Ticket Queue, Administration)
- Citizen portal: SSR for complaint status lookup
- PWA: single codebase, responsive for browser + mobile
- Calls api-gateway REST APIs with JWT

## Key Design Decisions

### Single Writer Pattern
All writes go through db-writer service via REST. Solves SQLite
concurrent write limitation. db-writer serialises writes.
If db-writer pod restarts (Kubernetes handles in seconds), a
readiness probe prevents traffic routing until healthy.

### SQLite WAL Mode
- WAL (Write-Ahead Logging) allows multiple concurrent readers
- Single writer (db-writer pod) never contends
- Caffeine cache reduces read load on SQLite
- Persistent Volume Claim survives pod restarts
- Backup sidecar: copy file to GCS/S3 every 15 minutes

### Migration to Postgres (if needed)
db-writer uses Hibernate Panache. Dialect swap + schema migration
is the only change needed. All other services are unaware.
Document the trigger: > 5,000 writes/day sustained.

## Shared Environment Variables

```env
# Valkey
VALKEY_URL=redis://valkey:6379

# JWT
JWT_SECRET=<min 64 char>
JWT_EXPIRY_ACCESS=15m
JWT_EXPIRY_REFRESH=7d

# AI
AI_CORE_URL=http://ai-core:8001
DEFAULT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# DB Writer
DB_WRITER_URL=http://db-writer:8080

# App
APP_ENV=development   # development | production
TENANT_ID=default     # overridden per tenant in multi-tenant setup
```
