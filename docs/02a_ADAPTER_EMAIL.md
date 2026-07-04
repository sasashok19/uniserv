# Feature 02a — Adapter: Email

## Phase Scope
- **Phase 1:** Full implementation — IMAP polling + SMTP outbound
- **Phase 2:** Gmail/Outlook OAuth push notifications (optional upgrade)

## What This Module Does
Polls a configured mailbox via IMAP. Normalises each email to the
canonical `ChannelMessageReceived` event. Sends outbound replies via SMTP.

## Boundaries
**Owns:** IMAP polling, email parsing, SMTP outbound.
**Does not own:** Identity resolution, AI, ticket logic.

---

## Identity
- `channelIdentity.type = "email"`
- `channelIdentity.value = from_address`
- `channelIdentity.verified = false` — identity gate will trigger

---

## Implementation

```java
// services/api-gateway/src/main/java/com/uniserve/adapters/email/EmailAdapter.java
@ApplicationScoped
public class EmailAdapter {

    @Scheduled(every = "{email.poll.interval}")
    void poll() {
        // 1. Connect IMAP
        // 2. Fetch unseen messages
        // 3. Parse → ChannelMessageReceived
        // 4. Publish to Valkey
        // 5. Mark as seen
    }

    public void sendReply(String toAddress, String subject,
                          String body, String inReplyToMessageId) {
        // SMTP send
    }
}
```

## Thread Detection
Use `In-Reply-To` and `References` headers → `threadId`.
No threading headers → `threadId = null` (new conversation).

---

## Environment Variables

```env
EMAIL_IMAP_HOST=imap.example.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USER=complaints@example.com
EMAIL_IMAP_PASSWORD=...
EMAIL_IMAP_MAILBOX=INBOX
EMAIL_IMAP_POLL_INTERVAL=60s
EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=complaints@example.com
EMAIL_SMTP_PASSWORD=...
EMAIL_FROM_ADDRESS=complaints@example.com
```

---

## Test Stubs

```http
### Trigger manual email poll (dev only)
POST http://localhost:8080/api/v1/internal/adapters/email/poll
Authorization: Bearer {{admin_token}}

### Expected
HTTP/1.1 200 OK
{ "messagesProcessed": 3, "errors": 0 }

### Send test outbound email
POST http://localhost:8080/api/v1/internal/adapters/email/test-send
Content-Type: application/json
Authorization: Bearer {{admin_token}}

{
  "to": "test@example.com",
  "subject": "Test reply from UniServe",
  "body": "Your complaint reference is TKT-00001"
}

### Expected
HTTP/1.1 200 OK
{ "sent": true }
```

---

## Mock Data Seed

```java
// packages/test-stubs/seed/EmailSeed.java
// Inserts 5 pre-parsed email events into Valkey stream on APP_ENV=development
// Simulates: billing complaint, power outage, general feedback,
//            anonymous request, follow-up reply on existing thread
```

---

## Testing
- Email with `From: John <john@example.com>` → identity email = john@example.com, verified = false
- HTML email → strips tags, extracts plain text
- Reply email → `threadId` matches parent
- SMTP send → no exception thrown

---

## Phase 1 Implementation Notes (deviations & corrections)
- IMAP polling uses `org.eclipse.angus:angus-mail`. When `EMAIL_IMAP_HOST` is unset (dev), `poll` is a no-op returning `{messagesProcessed:0, errors:0}` — the doc's `3` is illustrative of a populated mailbox.
- SMTP send uses the Quarkus mailer in **mock mode** (dev) — `test-send` returns `{sent:true}` without real delivery.
- MIME parsing is pure/unit-tested: From→identity (`verified:false`), HTML→text, `In-Reply-To`/`References`→`threadId`.
