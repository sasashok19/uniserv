# Feature 02b — Adapter: WhatsApp

## Phase Scope
- **Phase 1:** Full implementation — Meta WhatsApp Business API webhooks
- **Phase 2:** No changes

## What This Module Does
Receives inbound WhatsApp messages via Meta webhook. Normalises to canonical
event. Sends outbound replies via Graph API. Identity is pre-confirmed
(phone number always available from Meta).

## Boundaries
**Owns:** Webhook endpoint, HMAC validation, message parsing, outbound send.
**Does not own:** Identity resolution, AI, ticket logic.

---

## Identity
- `channelIdentity.type = "phone"`
- `channelIdentity.value = sender in E.164 format`
- `channelIdentity.verified = true` — identity gate SKIPPED

---

## Webhook Endpoint

```
POST /api/v1/webhooks/whatsapp
GET  /api/v1/webhooks/whatsapp   ← Meta hub.verify_token handshake
```

Every inbound POST must be validated with `X-Hub-Signature-256` (HMAC-SHA256).
Respond `200 OK` within 5 seconds. Process async.

```java
@Path("/api/v1/webhooks/whatsapp")
public class WhatsAppWebhookResource {

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Response receive(@HeaderParam("X-Hub-Signature-256") String sig,
                            String body) {
        if (!validateSignature(sig, body)) return Response.status(401).build();
        eventBus.publish(buildEvent(body));
        return Response.ok().build();
    }
}
```

## Supported Message Types (Phase 1)

| Type | Handling |
|---|---|
| text | → rawText |
| image / document | → rawMediaUrls |
| audio | → rawMediaUrls, flag for STT (Phase 2) |
| interactive button reply | → extract button title as rawText |

---

## Environment Variables

```env
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...          # for HMAC validation
WHATSAPP_ACCESS_TOKEN=...        # per-tenant, stored in DB
WHATSAPP_PHONE_NUMBER_ID=...     # per-tenant, stored in DB
```

---

## Test Stubs

```http
### Simulate inbound WhatsApp text message
POST http://localhost:8080/api/v1/webhooks/whatsapp
Content-Type: application/json
X-Hub-Signature-256: sha256=test_bypass_in_dev

{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{
          "from": "919876543210",
          "id": "wamid.test001",
          "timestamp": "1719475200",
          "text": { "body": "My electricity bill is double this month" },
          "type": "text"
        }],
        "contacts": [{ "profile": { "name": "Rajesh Kumar" } }]
      }
    }]
  }]
}

### Expected
HTTP/1.1 200 OK

### Verify event was published
GET http://localhost:8080/api/v1/internal/events/latest?stream=channel.message.received
Authorization: Bearer {{admin_token}}

### Expected
HTTP/1.1 200 OK
{
  "channel": "whatsapp",
  "channelIdentity": { "type": "phone", "value": "+919876543210", "verified": true },
  "rawText": "My electricity bill is double this month"
}
```

---

## Mock Data Seed

```java
// packages/test-stubs/seed/WhatsAppSeed.java
// Inserts 5 pre-parsed WhatsApp events into Valkey on APP_ENV=development
// Simulates: billing, meter fault, service complaint, anonymous, follow-up
```

---

## Testing
- Invalid HMAC → 401 returned, event NOT published
- Phone normalised to E.164 (`+91...`)
- `verified = true` always for WhatsApp
- 200 returned within 100ms (async processing)
