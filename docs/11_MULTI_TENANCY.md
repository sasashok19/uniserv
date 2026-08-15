# Feature 11 — Multi-Tenancy & Auth

## Phase Scope
- **Phase 1:** Full implementation — JWT, RBAC, tenant config
- **Phase 2:** LDAP/AD integration option for enterprise clients

## What This Module Does
JWT auth, role-based access control, tenant isolation, agent management.
Every API request is scoped to a tenant. Agents only see their tenant's data.

---

## Roles & Permissions

```java
public enum AgentRole { ADMIN, LEAD, AGENT }

public class RbacPolicy {
    // Returns true if role can perform action
    public boolean can(AgentRole role, String action) {
        return switch (action) {
            // Ticket viewing
            case "ticket.view.all"     -> role == ADMIN || role == LEAD;
            case "ticket.view.own"     -> true;
            // Ticket editing
            case "ticket.edit"         -> role == ADMIN || role == LEAD;
            case "ticket.note.add"     -> true;
            case "ticket.priority.edit"-> role == ADMIN || role == LEAD;
            case "ticket.assignee.edit"-> role == ADMIN || role == LEAD;
            // Status transitions
            case "ticket.status.open_to_assigned"     -> role == ADMIN || role == LEAD;
            case "ticket.status.assigned_to_inprogress"-> true;
            case "ticket.status.inprogress_to_resolved"-> true;
            case "ticket.status.resolved_to_closed"   -> role == ADMIN || role == LEAD;
            case "ticket.status.closed_to_reopened"   -> role == ADMIN || role == LEAD;
            // AI summary
            case "ticket.resolution.generate" -> true;
            // Export
            case "ticket.export"       -> role == ADMIN || role == LEAD;
            // Administration tab
            case "admin.view"          -> role == ADMIN;
            case "admin.agents.manage" -> role == ADMIN;
            case "admin.tenant.config" -> role == ADMIN;
            default -> false;
        };
    }
}
```

---

## JWT Structure

### Access Token (15 min)
```json
{
  "sub": "agent_uuid",
  "tenant_id": "tenant_uuid",
  "role": "agent",
  "name": "Rajesh Kumar",
  "email": "rajesh@example.com",
  "exp": 1234567890
}
```

### Refresh Token
- Stored in `HttpOnly` cookie
- Rotated on every use
- Revocation list in Valkey

---

## Auth Endpoints (api-gateway)

```
POST /api/v1/auth/login           → { access_token, expires_in }
POST /api/v1/auth/refresh         → { access_token }
POST /api/v1/auth/logout          → 200 (revokes refresh token)
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
```

---

## Agent Management Endpoints (api-gateway, Admin only)

```
GET    /api/v1/agents             → list agents
POST   /api/v1/agents             → create agent
PATCH  /api/v1/agents/{id}        → update (role, name, active)
DELETE /api/v1/agents/{id}        → deactivate (soft delete)
```

---

## Tenant Config Endpoints (Admin only)

```
GET  /api/v1/tenant/config        → get config
PUT  /api/v1/tenant/config        → update config
```

Config JSON structure:
```json
{
  "categories": {
    "billing": ["incorrect_amount", "payment_not_reflected"],
    "outage": ["power_cut", "low_voltage", "no_supply"]
  },
  "sla": {
    "critical": { "response_hours": 1, "resolution_hours": 4 },
    "default": { "response_hours": 4, "resolution_hours": 48 }
  },
  "identity_timeout_hours": 48,
  "anonymous_allowed": true,
  "channels_enabled": ["email", "whatsapp"],
  "llm_provider": "anthropic"
}
```

### Implementation note — merge-one-key resources

`TenantConfigResource` above **replaces the whole `config_json` object**. Every
later config feature therefore got its own resource that reads the blob, edits a
single key and writes it back, so two admin screens can never clobber each
other's settings:

| Key | Resource | Endpoint |
|---|---|---|
| `intakeFields` | `IntakeFieldsResource` | `GET|PUT /api/v1/tenant/intake-fields` |
| `priorityRubric` | `PriorityRubricResource` | `GET|PUT /api/v1/tenant/priority-rubric` |
| `generalSettings` | `GeneralSettingsResource` | `GET|PUT /api/v1/tenant/general-settings` |
| `landingPage` | `LandingPageResource` | `GET|PUT /api/v1/tenant/landing-page` |

All four gate on the same `admin.tenant.config` RBAC action.

Two of these keys are also readable **without auth**, because the pages that
need them (login, landing) are public: `generalSettings.newsFeedUrl` via
`GET /api/v1/public/news-config`, and the whole of `landingPage` via
`GET /api/v1/public/landing-page`. Both live under the `/api/v1/public/`
segment, which `AuthFilter.isProtected` deliberately does not match, and both
expose only their own key — never the rest of `config_json`, which holds
routing rules and SLA targets. See the README's *Configurable landing page*
section for the validation rules that apply because that content reaches
`style`/`src`/`href` attributes on an unauthenticated page.

---

## Environment Variables

```env
JWT_SECRET=<min 64 char>
JWT_EXPIRY_ACCESS=15m
JWT_EXPIRY_REFRESH=7d
BCRYPT_ROUNDS=12
```

---

## Test Stubs

```http
### Login as admin
POST http://localhost:8080/api/v1/auth/login
Content-Type: application/json

{ "email": "admin@tneb.demo", "password": "Admin@123" }

### Expected
HTTP/1.1 200 OK
{ "access_token": "eyJ...", "expires_in": 900, "role": "admin" }

### Login as agent
POST http://localhost:8080/api/v1/auth/login
Content-Type: application/json

{ "email": "agent@tneb.demo", "password": "Agent@123" }

### Agent tries to access all tickets (should be denied)
GET http://localhost:8080/api/v1/tickets
Authorization: Bearer {{agent_token}}

### Expected
HTTP/1.1 403 Forbidden
{ "error": { "code": "INSUFFICIENT_ROLE", "message": "Agents can only view their assigned tickets" } }

### Agent accesses own tickets (allowed)
GET http://localhost:8080/api/v1/tickets?assignedTo=me
Authorization: Bearer {{agent_token}}

### Expected
HTTP/1.1 200 OK
{ "tickets": [...], "total": 5 }

### Admin creates new agent
POST http://localhost:8080/api/v1/agents
Authorization: Bearer {{admin_token}}
Content-Type: application/json

{ "name": "New Agent", "email": "newagent@tneb.demo", "role": "agent", "password": "TempPass@123" }

### Expected
HTTP/1.1 201 Created
{ "id": "uuid", "name": "New Agent", "role": "agent" }

### Lead tries to create agent (should fail)
POST http://localhost:8080/api/v1/agents
Authorization: Bearer {{lead_token}}
Content-Type: application/json

{ "name": "Test", "email": "test@tneb.demo", "role": "agent", "password": "Test@123" }

### Expected
HTTP/1.1 403 Forbidden

### Refresh token
POST http://localhost:8080/api/v1/auth/refresh
Cookie: refresh_token=...

### Expected
HTTP/1.1 200 OK
{ "access_token": "eyJ...", "expires_in": 900 }

### Expired token rejected
GET http://localhost:8080/api/v1/tickets
Authorization: Bearer {{expired_token}}

### Expected
HTTP/1.1 401 Unauthorized
{ "error": { "code": "TOKEN_EXPIRED", "message": "Access token expired" } }
```

---

## Testing
- Admin token → all endpoints accessible
- Lead token → admin endpoints return 403
- Agent token → all-tickets endpoint returns 403, own-tickets returns 200
- Expired token → 401
- Refresh token rotated → old refresh token rejected after use

---

## Phase 1 Implementation Notes (deviations & corrections)
- JWTs are **HS256 via `com.auth0:java-jwt`** with a shared `JWT_SECRET`, verified by a custom `AuthFilter`; password hashing/verification uses Quarkus `BcryptUtil`.
- `quarkus.smallrye-jwt.enabled=false` — the built-in MP-JWT mechanism would otherwise intercept and reject our HS256 Bearer tokens before the custom filter runs.
- On dev startup the gateway **reseeds the seed agents' bcrypt password hashes** (admin/lead/agent) so the documented dev credentials work.
- Refresh tokens are rotated with a Valkey-backed revocation entry. A dev-only helper `GET /api/v1/auth/_dev/expired-token` exists to exercise the `TOKEN_EXPIRED` path.
- **Feature 26 - `whatsappMenu`.** `GET|PUT /api/v1/tenant/whatsapp-menu`
  (`WhatsAppMenuResource`, `admin.tenant.config`) is the seventh consumer of the
  read-merge-write `config_json` pattern, alongside `generalSettings`,
  `intakeFields`, `intakeFieldCatalog`, `priorityRubric` and `landingPage`.
  It holds every string a citizen reads on WhatsApp plus `enabled` and
  `sessionTtlHours`.
  - `companyName` **cascades**: explicit value -> `landingPage.brandName` ->
    `"UniServe"`. A tenant that has already branded its public page should not
    have to type its own name again to brand WhatsApp.
  - Validation rejects a `menuPrompt` that has lost one of the option numbers
    (the branch stays reachable by typing but undiscoverable), a
    `ticketDetails`/`ticketCreated` without the `{ticket}` placeholder, and a
    `sessionTtlHours` outside 1-24.
  - `sessionTtlHours` is clamped on **read** as well as write, because
    `TenantConfigResource` replaces the whole `config_json` blob and a
    `whatsappMenu` object can therefore reach the database without ever passing
    through `normalise` - the same trap documented for the landing page.
  - There is **no public counterpart** to this resource. Unlike the landing
    page, nothing renders this content to an anonymous browser: ai-core reads
    the stored blob directly from db-writer over the internal network.
  - `app/conversation/menu_content.py` mirrors the Java defaults, and
    `services/ai-core/tests/test_menu_content.py` parses
    `WhatsAppMenuContent.java` and fails on any drift - key set, every default
    string, and the TTL bounds. Without that guard the admin screen and the
    citizen could silently disagree about what the welcome message says.
