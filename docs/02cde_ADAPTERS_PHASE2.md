# Feature 02c — Adapter: Twitter/X
# Feature 02d — Adapter: IVR
# Feature 02e — Adapter: Web Chat

## Phase Scope
- **Phase 1:** DO NOT IMPLEMENT. Stub files only.
- **Phase 2:** Full implementation.

---

## PHASE 2 ONLY — Twitter/X (02c)

Connects to Twitter Filtered Stream API v2. Monitors mentions of the
tenant's handle. Sends outbound replies via Twitter API.

Identity: `type=handle`, `verified=false` — identity gate triggers.

Key feature: tweets tagging minister/director handles get elevated
priority score and trigger 15-minute SLA alert.

Implementation details deferred to Phase 2.

---

## PHASE 2 ONLY — IVR / Twilio Voice (02d)

Handles inbound voice calls via Twilio. Uses Twilio STT to transcribe
complaint. Sends TTS replies back to caller.

Identity: `type=phone`, `verified=true` (unless caller withheld).

Language: default `en-IN`, configurable per tenant (`ta-IN`, `hi-IN`).

Implementation details deferred to Phase 2.

---

## PHASE 2 ONLY — Web Chat Widget (02e)

Embeddable JS widget (`<script>` tag). Real-time via WebSocket server
in api-gateway.

Identity: `type=session`, `verified=false` — identity gate always triggers.

Pre-auth option: tenant websites with logged-in users can pass identity
token at widget init → skips identity gate.

Implementation details deferred to Phase 2.

---

## Phase 1 Placeholder Endpoints

```http
### Twitter adapter status (Phase 2 stub)
GET http://localhost:8080/api/v1/adapters/twitter/status
Authorization: Bearer {{admin_token}}

### Expected Phase 1 response
HTTP/1.1 503 Service Unavailable
{ "error": { "code": "PHASE_2_FEATURE", "message": "Twitter adapter available in Phase 2" } }
```
