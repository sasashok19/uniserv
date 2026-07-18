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
- IMAP polling uses `org.eclipse.angus:angus-mail`. When `EMAIL_IMAP_HOST` resolves to blank, `poll`/`pollOnce()` is a no-op returning `{messagesProcessed:0, errors:0}` — the doc's `3` above is illustrative of a populated mailbox. In this repo's config, `email.imap.host` defaults to `imap.gmail.com` (non-blank), so polling is **on by default**; a totally fresh clone with no `EMAIL_SMTP_USER`/`PASSWORD` configured will see periodic benign IMAP-auth-failure log lines every `email.poll.interval` until real credentials are set — harmless, just noisy.
- SMTP send uses the Quarkus mailer; `test-send` returns `{sent:<bool>}`. Set `EMAIL_SMTP_MOCK=true` to fall back to logging instead of a real send.
- **Correction — App Passwords cover Gmail IMAP too (Make.com is not required):** an earlier version of this doc claimed Gmail/Outlook both require OAuth2 for IMAP, which was the reason Make.com existed as a webhook relay for inbound mail. That was wrong for Gmail specifically. Verified against Google's own support docs: Google retired **"Less Secure Apps"** (bare password, no 2FA) in 2022, but **App Passwords** (2-Step Verification > App passwords) remain fully supported for **both IMAP and SMTP**. The same App Password already used for outbound SMTP authenticates IMAP too (`imap.gmail.com:993`, SSL) — no OAuth2, no public tunnel, no Make.com needed. This does **not** apply to Microsoft 365/Outlook, which fully retired Basic Auth for mail protocols in Sept 2024 with no app-password equivalent — a webhook relay (Make.com or similar) is still the right call there.
- **IMAP polling revived (Make.com webhook removed):** `EmailWebhookResource`/`EmailWebhookSecretValidator` and `EMAIL_WEBHOOK_SECRET` are gone — `POST /api/v1/webhooks/email` now 404s. `EmailAdapter.scheduledPoll()`/`pollOnce()` connect via IMAP, parse each unseen message to `ChannelMessageReceived`, validate via `EventValidator`, publish on success (or count as an error on validation failure), and flag the message `SEEN`. `email.imap.user`/`password` default to the SMTP credential (`EMAIL_IMAP_USER:${EMAIL_SMTP_USER:}`) via `application.properties` nested-default syntax, so one Gmail App Password drives both directions with no extra config in the common case.
- **Inbound `Message-ID` is now captured end-to-end.** `EmailAdapter.parseMessage`/`extractMessageId` reads the inbound email's own `Message-ID` header and puts it on `ChannelMessageReceived.messageId` (a new field, with a backward-compatible constructor overload for older callers). Downstream it's persisted as `tickets.origin_message_id` (db-writer, migration `V7__ticket_origin_message_id.sql`), set once when the ticket stub is created.
- **Outbound replies thread into the original chain (RFC 5322).** `EmailAdapter.sendReply(...)` already accepted an `inReplyToMessageId` param (sets `In-Reply-To` + `References`), but every caller hard-coded `null`, so acks/updates/status-changes arrived as disconnected new emails. Now `EmailAdapterResource` (`/test-send`), `TicketsResource.reply()`, `TicketNotifier.sendStatusUpdateEmail()`, and ai-core's `app/notifications/sender.py` all forward the stored `origin_message_id`, so every reply lands in the same email chain the citizen started. See the README's *Subject-line ticket threading & dedup* section.
- **Thread-key collapse fix (ai-core side).** Complementary to threading: `ConversationAgent._thread_key()` no longer falls back to `email:<address>` (shared by every email from that sender, which collapsed unrelated new complaints onto old tickets) — it now uses `email:<message-id>` when there's no real `In-Reply-To`. WhatsApp's per-phone thread key is unchanged. Regression-tested in `services/ai-core/tests/test_thread_key.py`.
- **Outbound SMTP is real, not mock, by default** (Phase 1, config-only — `EmailAdapter.sendReply()`/`test-send` are unchanged Java code). `quarkus.mailer.mock` defaults to `${EMAIL_SMTP_MOCK:false}`. Verified working against Gmail SMTP (`smtp.gmail.com:587`, STARTTLS) using an account App Password (requires 2-Step Verification). One easy-to-miss requirement: `quarkus.mailer.auth-methods=PLAIN LOGIN` **must** be set explicitly — Gmail advertises XOAUTH2 first, and without this the mailer tries XOAUTH2 (no token available) instead of the App Password and every send fails. `EMAIL_FROM_ADDRESS` should match `EMAIL_SMTP_USER` (or a verified Gmail alias) or Gmail may reject/bounce the send.
