# UniServe — Project Orchestrator

## Product Vision
A multi-tenant AI-powered complaint and feedback portal that unifies inbound
messages from Email and WhatsApp (Phase 1), and Twitter, IVR, and Web Chat
(Phase 2) into a single intelligent queue. The AI confirms identity, gathers
missing details, deduplicates cross-channel complaints, classifies, and
prioritises for agents — with role-based access control, a structured
sign-off workflow, and full audit trail. Deployable on GKE, AWS, Azure, or
own cloud via Docker + Kubernetes.

---

## Phase Map

### Phase 1 — Build this first
- Email + WhatsApp channels only
- Core AI: identity gate, PII scrubber (basic), classification, priority
- DB Writer Service + SQLite WAL
- Agent Dashboard: all three tabs, full RBAC, ticket workflow
- Notifications: outbound email only
- Mock data seed for development
- Test stubs for all endpoints

### Phase 2 — Do not build until Phase 1 is complete
- Twitter, IVR, Web Chat channels
- Field-level AES-256-GCM encryption (PiiEncryptionService)
- Blind indexes for PII search
- KMS / Vault key management
- Key rotation job
- SMS + webhook notifications
- Full no-PII logging enforcement

**When starting a session:** Tell the AI assistant which phase you are
implementing. Example: "Implement Phase 1 only. Do not scaffold any
Phase 2 code."

---

## Monorepo Structure

```
uniserve/
├── services/
│   ├── api-gateway/          # Quarkus — REST API, channel adapters, auth
│   ├── db-writer/            # Quarkus — sole DB writer, SQLite WAL
│   └── ai-core/              # Python FastAPI — AI pipeline
├── apps/
│   └── dashboard/            # Next.js PWA — agent UI + citizen portal
├── packages/
│   ├── event-contracts/      # Shared event schemas (JSON)
│   └── test-stubs/           # .http test files + mock seed scripts
├── infrastructure/
│   ├── docker/               # Dockerfiles per service
│   ├── k8s/                  # Kubernetes manifests
│   └── compose/              # docker-compose for local dev
└── docs/
    ├── ORCHESTRATOR.md
    ├── architecture/
    └── features/
```

---

## Tech Stack

| Layer | Technology | Phase |
|---|---|---|
| Backend API + Adapters | Quarkus Java 21 | P1 |
| AI Services | Python 3.11 / FastAPI | P1 |
| Inter-service messaging | Valkey (Redis-compatible, MIT) | P1 |
| DB Writer Service | Quarkus Java 21 | P1 |
| Database | SQLite 3 in WAL mode | P1 |
| Read cache | Caffeine (in DB Writer pod) | P1 |
| Frontend | Next.js 14 / Tailwind / shadcn/ui / PWA | P1 |
| Containers | Docker | P1 |
| Orchestration | Kubernetes (GKE Autopilot preferred) | P1 |
| Phase 2 Encryption | AES-256-GCM + Cloud KMS / Vault | P2 |

---

## Shared Conventions

### Naming
- Java files: `PascalCase.java`
- Python files: `snake_case.py`
- REST endpoints: `/api/v1/{resource}/{id}/{action}`
- Event names: `{domain}.{entity}.{verb}` past tense
- SQLite columns: `snake_case`
- Phase 2 fields: marked `-- PHASE_2_ENCRYPT` in schema

### Phase Markers in Code
```java
// PHASE_1: basic PII handling
// PHASE_2: replace with PiiEncryptionService.encrypt()
String email = request.getEmail();
```

```python
# PHASE_1: log token only
# PHASE_2: enforce no-PII logging filter
logger.info(f"Processing ticket {ticket_id}")
```

### Error Handling
- All APIs return `{ "error": { "code": "...", "message": "...", "details": {} } }`
- Never expose stack traces to clients
- AI failures (LLM down, timeout) return graceful degraded responses

### Logging
- Structured JSON: `level`, `timestamp`, `service`, `tenant_id`, `trace_id`, `message`
- Phase 1: no PII in log messages by convention
- Phase 2: enforced by log filter

### Environment Variables
- Every service has `.env.example`
- Never commit `.env`
- Prefix by service: `DB_WRITER_*`, `AI_CORE_*`, `GATEWAY_*`

---

## Feature Build Order

| Order | File | Description | Phase | Depends On |
|---|---|---|---|---|
| 1 | `01_EVENT_BUS.md` | Valkey streams setup | P1 | — |
| 2 | `02f_ADAPTER_CONTRACT.md` | Shared event schema | P1 | 01 |
| 3 | `02a_ADAPTER_EMAIL.md` | Email adapter | P1 | 02f |
| 4 | `02b_ADAPTER_WHATSAPP.md` | WhatsApp adapter | P1 | 02f |
| 5 | `02c_ADAPTER_TWITTER.md` | Twitter adapter | P2 | 02f |
| 6 | `02d_ADAPTER_IVR.md` | IVR adapter | P2 | 02f |
| 7 | `02e_ADAPTER_WEBCHAT.md` | Web chat adapter | P2 | 02f |
| 8 | `03_IDENTITY_RESOLVER.md` | Cross-channel identity merge | P1 | 01, 05 |
| 9 | `04_DB_WRITER_SERVICE.md` | Single writer + SQLite WAL | P1 | — |
| 10 | `05_TICKET_SCHEMA.md` | SQLite schema + migrations | P1 | — |
| 11 | `06_AI_CONVERSATION.md` | Identity gate + info gathering | P1 | 01, 03 |
| 12 | `07_PII_SCRUBBER.md` | PII scrubbing + P2 encryption | P1+P2 | 06 |
| 13 | `08_CLASSIFICATION.md` | Category + intent + sentiment | P1 | 06, 07 |
| 14 | `09_DEDUPLICATION.md` | Cross-channel dedup | P1 | 08 |
| 15 | `10_PRIORITY_ENGINE.md` | AI priority scoring | P1 | 08, 09 |
| 16 | `11_MULTI_TENANCY.md` | JWT, RBAC, tenant config | P1 | 05 |
| 17 | `12_AGENT_DASHBOARD.md` | Next.js UI — all tabs | P1 | 10, 11 |
| 18 | `13_ANALYTICS.md` | Charts, SLA, trends | P1 | 12 |
| 19 | `14_NOTIFICATIONS.md` | Email (P1) + SMS/webhook (P2) | P1+P2 | 05, 11 |
| 20 | `15_ENCRYPTION_SERVICE.md` | Field-level encryption | P2 | 05, 11 |
| 21 | `16_DEPLOYMENT.md` | Docker + K8s + GKE | P1 | All |

---

## RBAC Summary

| Capability | Admin | Lead | Agent |
|---|---|---|---|
| View Analytics tab | ✅ | ✅ | ✅ read-only |
| View all tickets | ✅ | ✅ | ❌ own only |
| View own tickets | ✅ | ✅ | ✅ |
| Add notes | ✅ | ✅ | ✅ |
| Status: Open→Assigned | ✅ | ✅ | ❌ |
| Status: Assigned→In-Progress | ✅ | ✅ | ✅ |
| Status: In-Progress→Resolved | ✅ | ✅ | ✅ + mandatory note |
| Status: Resolved→Closed | ✅ | ✅ | ❌ |
| Status: Closed→Reopened | ✅ | ✅ | ❌ + mandatory note |
| Change priority | ✅ | ✅ | ❌ |
| Change assignee | ✅ | ✅ | ❌ |
| Edit ticket fields | ✅ | ✅ | ❌ |
| Generate AI summary | ✅ | ✅ | ✅ |
| Export tickets CSV | ✅ | ✅ | ❌ |
| View Administration tab | ✅ | ❌ | ❌ |
| Manage agents | ✅ | ❌ | ❌ |
| Configure tenant | ✅ | ❌ | ❌ |

---

## Ticket Status Flow

```
Open → Assigned → In-Progress → Resolved → Closed
                                              ↓
                                          Reopened → In-Progress
```

Mandatory note minimums:
- In-Progress → Resolved: 20 characters
- Resolved → Closed: 20 characters
- Closed → Reopened: 20 characters
- Assigned → In-Progress: optional

On Reopen:
- Assigned to same agent who closed it
- Lead gets notification
- Resolution field cleared
- Previous resolution preserved in notes timeline

---

## Session Start Template

```
I am building UniServe — a multi-tenant AI complaint portal.
Context: ORCHESTRATOR.md

Today I am implementing: [feature name — e.g. 04_DB_WRITER_SERVICE]
Phase: Phase 1 ONLY. Do not scaffold any Phase 2 code.

Completed: [list]
In progress: [this feature]

Constraints:
- Do not touch files outside the scope of the feature MD
- Add // PHASE_2 markers where Phase 2 will extend this
- Run test stubs after implementation and confirm they pass
```
