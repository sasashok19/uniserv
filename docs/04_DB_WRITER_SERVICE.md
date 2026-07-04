# Feature 04 — DB Writer Service

## Phase Scope
- **Phase 1:** Full implementation — SQLite WAL, Caffeine cache, REST API
- **Phase 2:** Add PiiEncryptionService, blind index writes, key rotation job

## What This Module Does
The ONLY service that writes to SQLite. Exposes REST API for all reads
and writes. All other pods call this service — they never touch SQLite
directly. Serialises all writes. Caffeine cache serves hot reads from memory.

## Boundaries
**Owns:** SQLite connection, Flyway migrations, all CRUD operations,
Caffeine cache, backup sidecar trigger.
**Does not own:** Business logic, AI, authentication (JWT verified by api-gateway).

---

## Architecture

```
Any Pod → REST → DB Writer → Caffeine (cache hit → return)
                           → SQLite (cache miss → read/write)
```

Single pod in Kubernetes. Cannot be horizontally scaled (by design).
Vertical scale only. Readiness probe prevents traffic until healthy.

---

## Key Implementation Details

### Quarkus + Hibernate Panache + SQLite

```java
// application.properties
quarkus.datasource.db-kind=other
quarkus.datasource.jdbc.driver=org.sqlite.JDBC
quarkus.datasource.jdbc.url=${DB_WRITER_SQLITE_PATH:jdbc:sqlite:/data/uniserve.db?journal_mode=WAL}
quarkus.flyway.migrate-at-start=true
quarkus.flyway.locations=classpath:db/migration
```

### Caffeine Cache

```java
@ApplicationScoped
public class TicketCache {

    private final Cache<String, Ticket> cache = Caffeine.newBuilder()
        .maximumSize(1000)
        .expireAfterWrite(Duration.ofMinutes(2))
        .build();

    public Optional<Ticket> get(String ticketId) { ... }
    public void put(Ticket ticket) { ... }
    public void invalidate(String ticketId) { ... }
}
```

Cache keys: `ticket:{id}`, `tenant_config:{tenantId}`, `agent:{id}`.
TTL: 2 minutes. Invalidated on write.

### Write Serialisation

Quarkus processes requests on the Vert.x event loop.
SQLite WAL handles concurrent reads cleanly.
Writes are synchronous and serialised by the single pod.

---

## REST API Endpoints

### Tickets
```
POST   /api/v1/db/tickets                   → create ticket
GET    /api/v1/db/tickets/{id}              → get by id
GET    /api/v1/db/tickets?tenantId=&...     → list with filters
PATCH  /api/v1/db/tickets/{id}              → update fields
GET    /api/v1/db/tickets/{id}/messages     → all messages
GET    /api/v1/db/tickets/{id}/notes        → all notes
GET    /api/v1/db/tickets/{id}/events       → audit trail
```

### Ticket Queue Filters (GET /api/v1/db/tickets)
```
tenantId       required
assignedTo     optional — filter by agent
status         optional — comma-separated e.g. open,assigned
priorityLabel  optional — critical,high,medium,low
channel        optional — email,whatsapp
category       optional
dateFrom       optional — ISO 8601
dateTo         optional — ISO 8601
identityStatus optional — confirmed,anonymous,pending
sortBy         optional — priority_score,created_at,updated_at
sortDir        optional — desc,asc (default: priority_score desc)
page           optional — default 1
pageSize       optional — default 20, max 100
```

### Notes
```
POST   /api/v1/db/tickets/{id}/notes        → add note
```

### Status Transitions
```
POST   /api/v1/db/tickets/{id}/transition
Body: { "toStatus": "in_progress", "noteContent": "...", "agentId": "..." }
```
Validates mandatory note rules. Returns 422 if note missing/too short.

### Identity
```
POST   /api/v1/db/identities               → create profile
GET    /api/v1/db/identities?email=        → find by email
GET    /api/v1/db/identities?phone=        → find by phone
PATCH  /api/v1/db/identities/{id}/merge    → merge two profiles
```

### Agents
```
POST   /api/v1/db/agents                   → create
GET    /api/v1/db/agents/{id}              → get
GET    /api/v1/db/agents?tenantId=         → list
PATCH  /api/v1/db/agents/{id}              → update
```

### Analytics
```
GET    /api/v1/db/analytics/volume         → ticket volume by day/channel
GET    /api/v1/db/analytics/sla            → SLA met/breached stats
GET    /api/v1/db/analytics/priority       → priority distribution
GET    /api/v1/db/analytics/agents         → per-agent performance
```

---

## Mandatory Note Validation

```java
public void validateTransition(String fromStatus, String toStatus,
                                String noteContent) {
    Set<String> mandatoryTransitions = Set.of(
        "in_progress->resolved",
        "resolved->closed",
        "closed->reopened"
    );
    String key = fromStatus + "->" + toStatus;
    if (mandatoryTransitions.contains(key)) {
        if (noteContent == null || noteContent.trim().length() < 20) {
            throw new ValidationException(
                "Note required (min 20 chars) for " + key + " transition");
        }
    }
}
```

---

## Backup Sidecar

Runs as a sidecar container in the same pod:
```yaml
# k8s/db-writer-deployment.yaml
containers:
  - name: db-backup
    image: uniserve/db-backup:latest
    env:
      - name: BACKUP_INTERVAL_MINUTES
        value: "15"
      - name: BACKUP_DESTINATION
        value: "gs://uniserve-backup/sqlite/"  # or s3:// or azblob://
    volumeMounts:
      - name: sqlite-data
        mountPath: /data
```

---

## Environment Variables

```env
DB_WRITER_SQLITE_PATH=jdbc:sqlite:/data/uniserve.db?journal_mode=WAL
DB_WRITER_PORT=8081
DB_WRITER_CACHE_MAX_SIZE=1000
DB_WRITER_CACHE_TTL_MINUTES=2
DB_WRITER_INTERNAL_API_KEY=...  # shared secret for pod-to-pod auth
BACKUP_INTERVAL_MINUTES=15
BACKUP_DESTINATION=gs://your-bucket/sqlite/
APP_ENV=development              # development | production
```

---

## Test Stubs

```http
### Create ticket
POST http://localhost:8081/api/v1/db/tickets
Content-Type: application/json
X-Internal-Key: {{internal_api_key}}

{
  "tenantId": "t1",
  "channelOrigin": "whatsapp",
  "identityId": "i1",
  "identityStatus": "confirmed",
  "category": "billing",
  "subcategory": "incorrect_amount",
  "priorityScore": 7.2,
  "priorityLabel": "high"
}

### Expected
HTTP/1.1 201 Created
{ "id": "uuid", "ticketNumber": "TKT-00001", "status": "open" }

### Get ticket with cache header
GET http://localhost:8081/api/v1/db/tickets/{{ticket_id}}
X-Internal-Key: {{internal_api_key}}

### Expected
HTTP/1.1 200 OK
X-Cache: HIT   ← on second request
{ "id": "...", "ticketNumber": "TKT-00001", ... }

### Status transition — valid
POST http://localhost:8081/api/v1/db/tickets/{{ticket_id}}/transition
Content-Type: application/json
X-Internal-Key: {{internal_api_key}}

{
  "fromStatus": "in_progress",
  "toStatus": "resolved",
  "noteContent": "Meter reading corrected after site visit. Bill revised.",
  "agentId": "a3"
}

### Expected
HTTP/1.1 200 OK
{ "status": "resolved", "resolvedAt": "2025-06-27T..." }

### Status transition — missing note (should fail)
POST http://localhost:8081/api/v1/db/tickets/{{ticket_id}}/transition
Content-Type: application/json
X-Internal-Key: {{internal_api_key}}

{
  "fromStatus": "in_progress",
  "toStatus": "resolved",
  "noteContent": "ok",
  "agentId": "a3"
}

### Expected
HTTP/1.1 422 Unprocessable Entity
{ "error": { "code": "NOTE_TOO_SHORT", "message": "Note must be at least 20 characters for in_progress->resolved transition" } }

### Analytics — ticket volume
GET http://localhost:8081/api/v1/db/analytics/volume?tenantId=t1&period=30d
X-Internal-Key: {{internal_api_key}}

### Expected
HTTP/1.1 200 OK
{ "data": [{ "date": "2025-06-01", "count": 12, "byChannel": { "email": 7, "whatsapp": 5 } }] }

### AI Resolution Summary
POST http://localhost:8081/api/v1/db/tickets/{{ticket_id}}/generate-resolution-summary
X-Internal-Key: {{internal_api_key}}

### Expected (AI available)
HTTP/1.1 200 OK
{ "summary": "Customer reported incorrect billing for March. Meter reading was corrected after site visit. Bill revised and resent." }

### Expected (AI unavailable)
HTTP/1.1 503 Service Unavailable
{ "error": { "code": "AI_UNAVAILABLE", "message": "AI summary unavailable. Please write resolution manually." } }
```

---

## Testing
- Create ticket → `TKT-00001` assigned sequentially per tenant
- Second GET for same ticket → `X-Cache: HIT`
- Transition `in_progress→resolved` without 20-char note → 422
- Transition `closed→reopened` → resolution field cleared, assignee preserved
- SQLite WAL → concurrent GET requests while write in progress succeed

---

## Phase 1 Implementation Notes (deviations & corrections)
- **Port 8090** (doc says 8081) — consistent across the stack.
- Data access is **plain JDBC over the Agroal `DataSource`** (not Hibernate Panache) for predictable SQLite behaviour. `db-kind=sqlite` via the Quarkiverse `quarkus-jdbc-sqlite` extension (the spec's `db-kind=other` + `org.sqlite.JDBC` does not exist as a Quarkus combo).
- `X-Internal-Key` is enforced **only when `DB_WRITER_INTERNAL_API_KEY` is set** (dev no-op).
- `generate-resolution-summary` returns **503 AI_UNAVAILABLE** in Phase 1 (AI summariser not wired to db-writer yet).
- Analytics: `volume` (04) + `sla`/`priority` (13) implemented; per-agent analytics deferred.
