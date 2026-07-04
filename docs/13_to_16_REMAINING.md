# Feature 13 — Analytics

## Phase Scope
- **Phase 1:** All analytics views
- **Phase 2:** No changes

## What This Module Does
Analytics data layer — SQL queries against SQLite via db-writer,
served to the dashboard. All views are tenant-scoped, date-filterable.

---

## Queries (run via db-writer)

```sql
-- Volume by day and channel
SELECT date(created_at) as day,
       channel_origin as channel,
       COUNT(*) as count
FROM tickets
WHERE tenant_id = ?
  AND created_at >= ?
GROUP BY day, channel
ORDER BY day;

-- SLA performance
SELECT
  COUNT(CASE WHEN resolved_at <= sla_due_at THEN 1 END) as met,
  COUNT(CASE WHEN resolved_at > sla_due_at
          OR (sla_due_at < datetime('now') AND resolved_at IS NULL)
        THEN 1 END) as breached,
  COUNT(*) as total
FROM tickets
WHERE tenant_id = ? AND created_at >= ?;

-- Priority distribution
SELECT priority_label, COUNT(*) as count
FROM tickets WHERE tenant_id = ? AND created_at >= ?
GROUP BY priority_label;

-- Agent performance (Lead/Admin only)
SELECT a.name, a.id,
  COUNT(t.id) as resolved,
  AVG(JULIANDAY(t.resolved_at) - JULIANDAY(t.created_at)) * 24 as avg_hours
FROM tickets t JOIN agents a ON t.assigned_to = a.id
WHERE t.tenant_id = ? AND t.resolved_at >= ?
GROUP BY a.id;
```

---

## Test Stubs

```http
### Volume last 30 days
GET http://localhost:8081/api/v1/db/analytics/volume?tenantId=t1&period=30d
X-Internal-Key: {{internal_api_key}}

### Expected (seed data)
HTTP/1.1 200 OK
{ "data": [{ "day": "2025-06-27", "byChannel": { "email": 3, "whatsapp": 4 } }] }

### SLA performance
GET http://localhost:8081/api/v1/db/analytics/sla?tenantId=t1&period=30d
X-Internal-Key: {{internal_api_key}}

### Expected
HTTP/1.1 200 OK
{ "met": 19, "breached": 3, "total": 22, "slaMetPercent": 86.4 }
```

---

# Feature 14 — Notifications

## Phase Scope
- **Phase 1:** Outbound email notifications (SMTP)
- **Phase 2:** SMS (Twilio), webhook (tenant integration)

## What This Module Does
Sends notifications to agents and customers on ticket events.

---

## Phase 1 Notification Events

| Event | Recipient | Message |
|---|---|---|
| Ticket created (confirmed) | Customer (email) | "Your complaint TKT-00001 has been registered" |
| Ticket created (anonymous) | — | (no email to send) |
| Identity timeout | — | (no email — no address) |
| Ticket resolved | Customer (email) | "Your complaint TKT-00001 has been resolved" |
| New critical ticket | All leads + admins | Agent alert email |
| SLA breach imminent (1hr) | Assigned agent + leads | SLA warning email |
| Ticket reopened | Assigned agent | Reopen notification |

## PHASE_2 Events (do not implement in Phase 1)
- SMS via Twilio for phone-confirmed customers
- Webhook POST to tenant-registered URL

---

## Template Engine

```java
// Jinja2-style templates (Qute in Quarkus)
// services/api-gateway/src/main/resources/templates/

// ticket_created.html
// ticket_resolved.html
// critical_alert.html
// sla_warning.html
// ticket_reopened.html
```

---

## Environment Variables

```env
# Phase 1
NOTIFICATION_SMTP_HOST=smtp.example.com
NOTIFICATION_SMTP_PORT=587
NOTIFICATION_SMTP_USER=...
NOTIFICATION_SMTP_PASSWORD=...
NOTIFICATION_FROM_EMAIL=noreply@uniserve.app

# Phase 2
# TWILIO_ACCOUNT_SID=...
# TWILIO_AUTH_TOKEN=...
# WEBHOOK_SIGNATURE_SECRET=...
```

---

## Test Stubs

```http
### Send test notification
POST http://localhost:8080/api/v1/internal/notifications/test
Content-Type: application/json
Authorization: Bearer {{admin_token}}

{
  "type": "ticket_created",
  "to": "test@example.com",
  "ticketNumber": "TKT-00001",
  "category": "Billing"
}

### Expected
HTTP/1.1 200 OK
{ "sent": true, "channel": "email" }
```

---

# Feature 15 — Encryption Service (PHASE 2 ONLY)

## Phase Scope
- **Phase 1:** DO NOT IMPLEMENT. File is planning only.
- **Phase 2:** Full implementation.

## What This Module Does
Field-level AES-256-GCM encryption for all PII fields.
Lives inside the db-writer service. All other services unaware.

---

## Phase 2 Implementation Plan

```java
// PHASE_2 ONLY — do not write this code in Phase 1

@ApplicationScoped
public class PiiEncryptionService {

    @Inject KmsClient kms;

    public String encrypt(String plaintext, String tenantId) {
        byte[] iv  = generateIV();
        byte[] key = kms.getKey(tenantId);  // from Cloud KMS or Vault
        byte[] ct  = AES256GCM.encrypt(plaintext.getBytes(), key, iv);
        return "AES256:" + base64(iv) + ":" + base64(ct);
    }

    public String decrypt(String ciphertext, String tenantId) { ... }

    public String blindIndex(String value, String tenantId) {
        byte[] pepper = kms.getHmacPepper(tenantId);
        return base64(HMAC_SHA256(normalise(value), pepper));
    }
}
```

## Phase 2 Schema Changes
- Add `@Convert(converter = PiiFieldConverter.class)` to all
  `-- PHASE_2_ENCRYPT` marked columns in 05_TICKET_SCHEMA.md
- Add `_idx` blind index columns
- Add Flyway migration: `V4__add_encryption.sql`

## Key Management Options
- GCP: Cloud KMS (managed HSM, per-tenant key ring)
- AWS: AWS KMS
- On-prem: HashiCorp Vault with Kubernetes auth

## Key Rotation
- Background job in db-writer
- Reads each record with old key → re-encrypts with new key
- Single writer pod = no race condition
- Runs during low-traffic window

---

# Feature 16 — Deployment

## Phase Scope
- **Phase 1:** Docker images + Kubernetes manifests + GKE Autopilot
- **Phase 2:** No structural changes (same infra, more pods)

## Docker Images

```
infrastructure/docker/
├── api-gateway.Dockerfile      # Quarkus native image (GraalVM)
├── db-writer.Dockerfile        # Quarkus native image
├── ai-core.Dockerfile          # Python 3.11 slim
├── dashboard.Dockerfile        # Next.js standalone
└── db-backup.Dockerfile        # Lightweight sidecar (alpine + gsutil)
```

### Quarkus Native Build
```dockerfile
FROM quay.io/quarkus/ubi-quarkus-native-image:22.3 AS build
COPY . .
RUN ./mvnw package -Pnative -DskipTests

FROM registry.access.redhat.com/ubi8/ubi-minimal
COPY --from=build /app/target/*-runner /app/runner
ENTRYPOINT ["/app/runner"]
# Memory: ~50MB per pod (vs ~300MB JVM)
```

---

## Kubernetes Manifests

```
infrastructure/k8s/
├── namespace.yaml
├── configmap.yaml              # non-secret config
├── secrets.yaml                # JWT_SECRET, API keys (use K8s Secrets)
├── valkey-deployment.yaml
├── api-gateway-deployment.yaml # N replicas, HPA
├── ai-core-deployment.yaml     # N replicas, HPA
├── db-writer-deployment.yaml   # 1 replica only + PVC + backup sidecar
├── dashboard-deployment.yaml   # N replicas
├── pvc.yaml                    # PersistentVolumeClaim for SQLite
└── ingress.yaml                # HTTPS termination
```

### db-writer Deployment (key constraints)

```yaml
# k8s/db-writer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 1          # MUST be 1 — single writer
  strategy:
    type: Recreate     # Not RollingUpdate — prevents two writers briefly
  template:
    spec:
      containers:
        - name: db-writer
          image: uniserve/db-writer:latest
          readinessProbe:
            httpGet:
              path: /q/health/ready
              port: 8081
            initialDelaySeconds: 5
            periodSeconds: 3
          volumeMounts:
            - name: sqlite-data
              mountPath: /data
        - name: db-backup          # sidecar
          image: uniserve/db-backup:latest
          env:
            - name: BACKUP_INTERVAL_MINUTES
              value: "15"
          volumeMounts:
            - name: sqlite-data
              mountPath: /data
      volumes:
        - name: sqlite-data
          persistentVolumeClaim:
            claimName: sqlite-pvc
```

### Horizontal Pod Autoscaler (api-gateway, ai-core, dashboard)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## Docker Compose (local dev)

```yaml
# infrastructure/compose/docker-compose.dev.yml
services:
  valkey:
    image: valkey/valkey:7.2
    ports: ["6379:6379"]

  db-writer:
    build: { context: ../../, dockerfile: infrastructure/docker/db-writer.Dockerfile }
    ports: ["8081:8081"]
    volumes: ["sqlite-data:/data"]
    environment:
      APP_ENV: development

  api-gateway:
    build: { context: ../../, dockerfile: infrastructure/docker/api-gateway.Dockerfile }
    ports: ["8080:8080"]
    depends_on: [valkey, db-writer]

  ai-core:
    build: { context: ../../, dockerfile: infrastructure/docker/ai-core.Dockerfile }
    ports: ["8001:8001"]
    depends_on: [valkey, db-writer]

  dashboard:
    build: { context: ../../, dockerfile: infrastructure/docker/dashboard.Dockerfile }
    ports: ["3000:3000"]
    depends_on: [api-gateway]

volumes:
  sqlite-data:
```

---

## GKE Autopilot Setup

```bash
# Create cluster
gcloud container clusters create-auto uniserve \
  --region=asia-south1 \
  --release-channel=regular

# Deploy
kubectl apply -f infrastructure/k8s/

# Verify
kubectl get pods -n uniserve
kubectl get hpa -n uniserve
```

---

## Installer Checklist

```
Pre-deployment:
□ Docker Engine 24+ installed
□ kubectl configured for target cluster
□ Kubernetes secrets populated (JWT_SECRET, API keys)
□ Persistent disk quota confirmed (10GB minimum for SQLite PVC)
□ Backup destination bucket created (GCS/S3/Azure Blob)
□ SMTP credentials tested

Deployment:
1. kubectl apply -f k8s/namespace.yaml
2. kubectl apply -f k8s/secrets.yaml
3. kubectl apply -f k8s/pvc.yaml
4. kubectl apply -f k8s/valkey-deployment.yaml
5. kubectl apply -f k8s/db-writer-deployment.yaml
6. kubectl rollout status deployment/db-writer -n uniserve
7. kubectl apply -f k8s/api-gateway-deployment.yaml
8. kubectl apply -f k8s/ai-core-deployment.yaml
9. kubectl apply -f k8s/dashboard-deployment.yaml
10. kubectl apply -f k8s/ingress.yaml

Post-deployment:
□ Health check: curl https://your-domain/api/v1/health
□ Login with admin@tneb.demo (dev) or first-run admin setup
□ Verify backup sidecar running: kubectl logs -c db-backup
□ Check HPA: kubectl get hpa
```

---

## Test Stubs

```http
### Health check — all services
GET http://localhost:8080/api/v1/health

### Expected
HTTP/1.1 200 OK
{
  "status": "healthy",
  "services": {
    "apiGateway": "healthy",
    "dbWriter": "healthy",
    "aiCore": "healthy",
    "valkey": "healthy"
  }
}

### Health check — db-writer specifically
GET http://localhost:8081/q/health/ready

### Expected
HTTP/1.1 200 OK
{ "status": "UP" }

### Database backup status
GET http://localhost:8081/api/v1/internal/backup/status
X-Internal-Key: {{internal_api_key}}

### Expected
HTTP/1.1 200 OK
{ "lastBackup": "2025-06-27T10:15:00Z", "backupSizeKb": 2048, "destination": "gs://..." }
```

---

## Phase 1 Implementation Notes (deviations & corrections)
- **Ports:** all analytics/backup/health endpoints are on the running ports (db-writer **8090**, gateway **8080**) — docs say 8081.
- **13:** `analytics/volume` emits both `day` and `date` (+ `count` + `byChannel`); `analytics/sla` and `analytics/priority` implemented. SLA figures are data-dependent (0s until tickets have `sla_due_at` + `resolved_at`); the doc numbers are illustrative.
- **14:** message templates are **inline** (subject + HTML body per event type) rather than Qute `.html` files; the mailer runs in **mock mode** in dev (`{sent:true, channel:email}`).
- **15 Encryption:** **not implemented — Phase 2 only**, as the doc states.
- **16:** aggregate health is exposed at **`GET /api/v1/health`** (probes gateway/valkey/db-writer/ai-core). Phase-1 images are **JVM/Next-standalone** (native-image build is documented but not used). The **backup sidecar is k8s-only** (no-op in compose); `backup/status` reports live DB size + destination with `lastBackup:null`. Added k8s `configmap.yaml`, `secrets.yaml` (placeholders), `ingress.yaml`, `hpa.yaml`.
