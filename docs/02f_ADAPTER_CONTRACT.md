# Feature 02f — Adapter Contract

## Phase Scope
- **Phase 1:** Email + WhatsApp fields defined
- **Phase 2:** Twitter, IVR, WebChat channel types added (marked below)

## What This Module Does
Defines the canonical event schema all channel adapters must emit.
Read this before building any adapter (02a–02e).

---

## Canonical Event: `channel.message.received`

```java
public record ChannelMessageReceived(
    String id,
    String tenantId,
    String type,           // "channel.message.received"
    String timestamp,

    // Channel identity
    String channel,        // "email" | "whatsapp"
                           // PHASE_2: | "twitter" | "ivr" | "webchat"
    ChannelIdentity channelIdentity,

    // Content
    String rawText,
    List<String> rawMediaUrls,
    String languageHint,   // ISO 639-1 or null

    // Threading
    String threadId,
    String inReplyTo,      // message ID of parent, or null

    // Timestamps
    String sentAt,
    String receivedAt,

    String traceId
) {}

public record ChannelIdentity(
    String type,       // "phone" | "email" | "handle" | "session" | "unknown"
    String value,      // e.g. "+919876543210" or null
    boolean verified   // true = identity confirmed by channel natively
) {}
```

## Channel Identity Rules

| Channel | type | verified |
|---|---|---|
| WhatsApp | phone | **true** — identity gate skipped |
| Email | email | false — identity gate triggers |
| IVR (P2) | phone | true (unless withheld) |
| Twitter (P2) | handle | false |
| WebChat (P2) | session | false |

## Outbound Event: `ai.reply.send`

```java
public record AiReplySend(
    String channel,
    String threadId,
    String channelIdentityValue,
    String messageText,
    boolean isIdentityRequest,
    boolean isAnonymousAck,
    String ticketRefId        // null until ticket created
) {}
```

---

## Test Stubs

```http
### Validate adapter contract shape
POST http://localhost:8080/api/v1/internal/validate-event
Content-Type: application/json
Authorization: Bearer {{admin_token}}

{
  "type": "channel.message.received",
  "channel": "email",
  "channelIdentity": { "type": "email", "value": "test@example.com", "verified": false },
  "rawText": "My bill is wrong",
  "threadId": "thread-001",
  "sentAt": "2025-06-27T10:00:00Z"
}

### Expected response
HTTP/1.1 200 OK
{ "valid": true }
```

---

## Testing
- Email adapter emits `verified: false`
- WhatsApp adapter emits `verified: true`
- Missing required fields → validation rejects with 400
