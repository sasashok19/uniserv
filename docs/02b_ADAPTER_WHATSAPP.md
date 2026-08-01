# Feature 02b — Adapter: WhatsApp

## Phase Scope
- **Phase 1:** Full implementation — Meta WhatsApp Business API webhooks
- **Phase 2:** No changes

## What This Module Does
Receives inbound WhatsApp messages via Meta webhook. Normalises to canonical
event. Sends outbound replies via Graph API (`WhatsAppAdapter`, called from
ai-core's `app/notifications/sender.py` and from api-gateway's own
`TicketNotifier`/`TicketsResource` for status updates and agent replies —
the same pattern as the email adapter). Identity is pre-confirmed (phone
number always available from Meta).

## Boundaries
**Owns:** Webhook endpoint, HMAC validation, message parsing, outbound send
(`WhatsAppAdapter` + `WhatsAppAdapterResource`).
**Does not own:** Identity resolution, AI, ticket logic, pre-approved
template message management (see "24-hour customer service window" below —
not implemented).

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

This message's own wamid (`message.id`) is captured into `messageId`
(Feature 15 parity with email's `Message-ID`) — persisted as the ticket's
`origin_message_id` so an outbound reply can set Graph API's
`context.message_id` and render as a quoted reply-to in WhatsApp.

---

## Outbound Send

`WhatsAppAdapter.sendReply(toPhone, body, contextMessageId)` — called from
api-gateway's own citizen-notification code (`TicketNotifier`,
`TicketsResource`) and, for ai-core's `ai.reply.send` deliveries, via the
internal HTTP endpoint below (mirrors the email adapter's `/test-send`
pattern rather than ai-core talking to Meta directly).

```
POST /api/v1/internal/adapters/whatsapp/send
Content-Type: application/json

{ "to": "+919876543210", "body": "Your ticket TKT-00042 is now resolved.",
  "contextMessageId": "wamid.HBgL...=" }

### Expected
HTTP/1.1 200 OK
{ "sent": true }
```

Calls Meta's Graph API: `POST {WHATSAPP_GRAPH_API_BASE_URL}/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages`
with `{"messaging_product": "whatsapp", "to": "<digits, no leading +>", "type": "text", "text": {"body": ...}, "context": {"message_id": ...}}`,
`Authorization: Bearer {WHATSAPP_ACCESS_TOKEN}`. A non-2xx Graph API response
throws, which the caller (`TicketNotifier` — best-effort, logged; ai-core's
`sender.py` — reported to whoever triggered the send) treats the same as an
email send failure.

**24-hour customer service window (not worked around).** Meta only allows a
free-form text message within 24h of the citizen's last inbound message;
outside that window a pre-approved *template* message is required instead,
and this adapter doesn't implement template messages — the Graph API call
just fails. Identity requests/follow-ups happen inside an active
conversation so this rarely bites, but a resolve/close status update sent
days after the citizen went quiet could land outside the window and
silently fail (logged, not surfaced to the agent for the auto-close path;
surfaced as `sendError` in the dashboard for the manual reply path).

---

## Environment Variables

```env
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...          # for HMAC validation
WHATSAPP_ACCESS_TOKEN=...        # Graph API bearer token (System User token recommended)
WHATSAPP_PHONE_NUMBER_ID=...     # Meta's numeric phone_number_id (not the phone number itself)
WHATSAPP_API_VERSION=v21.0       # optional, defaults to v21.0 — bump if Meta retires it
```

`WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` are env-only in Phase 1
(not per-tenant DB config — this repo is single-tenant-per-deployment in
practice; per-tenant storage would be a Phase 2 multi-tenancy extension).

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
- Outbound: payload shape (messaging_product/to/type/text/context), leading
  `+` stripped from `to`, `context.message_id` set only when a
  `contextMessageId` is given, 4xx Graph API responses throw with the
  status+body preserved (`WhatsAppAdapterTest`, against a local stub HTTP
  server — no live Meta account needed to test this)
- Best-effort semantics: a failed WhatsApp send never blocks the ticket
  transition/reply-record write that triggered it (`TicketNotifierTest`,
  `TicketsResourceReplyTest`)

---

## Phase 1 Implementation Notes (deviations & corrections)
- Dev HMAC bypass token `sha256=test_bypass_in_dev` is accepted **only** when `APP_ENV=development`; otherwise real HMAC-SHA256 over the raw body is required.
- `events/latest` returns the reconstructed envelope + channel payload; `threadId` is `null` in Phase 1.
- Webhook/inspector endpoints are unauthenticated in Phase 1.
- Outbound send is unauthenticated too (`/api/v1/internal/adapters/whatsapp/send`, PHASE_1 — see 11_MULTI_TENANCY), same as the email adapter's `/test-send`.
- No pre-approved template message support — see "24-hour customer service window" above.
