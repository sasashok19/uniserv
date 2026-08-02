# Feature 02a — Adapter: Email

## Phase Scope
- **Phase 1:** Full implementation — IMAP polling + SMTP outbound
- **Phase 2:** Gmail/Outlook OAuth push notifications (optional upgrade)

## What This Module Does
Polls a configured mailbox via IMAP. Normalises each email to the
canonical `ChannelMessageReceived` event. Sends outbound replies via SMTP or,
when `EMAIL_PROVIDER=resend`, via Resend's HTTPS API — see "Outbound provider"
below for why the switch exists.

## Boundaries
**Owns:** IMAP polling, email parsing, outbound send (SMTP or Resend).
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

    public boolean sendReply(String toAddress, String subject,
                             String body, String inReplyToMessageId) {
        // EMAIL_PROVIDER=resend -> ResendEmailClient (HTTPS)
        // EMAIL_PROVIDER=smtp (default) -> Quarkus mailer (SMTP)
    }
}
```

## Thread Detection
Use `In-Reply-To` and `References` headers → `threadId`.
No threading headers → `threadId = null` (new conversation).

---

## Outbound provider: SMTP vs Resend

Render's free-tier web services block **all** outbound traffic to SMTP ports
25/465/587 (Render's own policy change, 2025-09-26) — direct Gmail SMTP from
api-gateway on Render just hangs until `ConnectTimeoutException` at 60s, no
matter the timeout or port tried. `EMAIL_PROVIDER` switches between:

- `smtp` (default) — the Quarkus mailer, direct Gmail SMTP. Works fine
  locally and on a paid Render plan (which lifts the 465/587 block; port 25
  stays blocked everywhere since Render runs on AWS EC2 and AWS blocks 25
  network-wide).
- `resend` — `ResendEmailClient` sends over Resend's HTTPS API instead
  (port 443 is never blocked). Required on Render's free tier for real
  outbound email to work at all.

`ResendEmailClient` (`services/api-gateway/.../adapters/email/ResendEmailClient.java`)
posts to `https://api.resend.com/emails` with a Bearer `RESEND_API_KEY`,
setting `In-Reply-To`/`References` as custom headers the same way the SMTP
path does, so reply-threading (see above) behaves identically either way.

**Sandbox limitation (no verified domain):** with `RESEND_FROM_ADDRESS`
still on `onboarding@resend.dev` (the default), Resend rejects sends to any
recipient other than the address that signed up for the Resend account
(403 `validation_error`) — this is Resend's own anti-abuse restriction, not
a UniServe bug. In this state, real outbound replies only succeed when the
citizen's email happens to be that same signup address; every other
recipient dead-letters after 3 retries. Verifying a domain at
resend.com/domains and sending from an address on it removes this
restriction entirely.

---

## Environment Variables

```env
EMAIL_IMAP_HOST=imap.example.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USER=complaints@example.com
EMAIL_IMAP_PASSWORD=...
EMAIL_IMAP_MAILBOX=INBOX
EMAIL_IMAP_POLL_INTERVAL=60s

# Outbound provider switch — see "Outbound provider: SMTP vs Resend" above.
EMAIL_PROVIDER=smtp
RESEND_API_KEY=
RESEND_FROM_ADDRESS=onboarding@resend.dev

# Used when EMAIL_PROVIDER=smtp
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
- `EMAIL_PROVIDER=resend` → `ResendEmailClient` used instead, same `{sent:<bool>}` contract
- `test-send` failure (e.g. Resend's sandbox 403) → `502` with `{sent:false, error:<real message>}`, not a bare `500` (`EmailAdapterResourceTest`)

---

## Phase 1 Implementation Notes (deviations & corrections)
- IMAP polling uses `org.eclipse.angus:angus-mail`. When `EMAIL_IMAP_HOST` resolves to blank, `poll`/`pollOnce()` is a no-op returning `{messagesProcessed:0, errors:0}` — the doc's `3` above is illustrative of a populated mailbox. In this repo's config, `email.imap.host` defaults to `imap.gmail.com` (non-blank), so polling is **on by default**; a totally fresh clone with no `EMAIL_SMTP_USER`/`PASSWORD` configured will see periodic benign IMAP-auth-failure log lines every `email.poll.interval` until real credentials are set — harmless, just noisy.
- SMTP send uses the Quarkus mailer; `test-send` returns `{sent:<bool>}`. Set `EMAIL_SMTP_MOCK=true` to fall back to logging instead of a real send.
- **Correction — App Passwords cover Gmail IMAP too (Make.com is not required):** an earlier version of this doc claimed Gmail/Outlook both require OAuth2 for IMAP, which was the reason Make.com existed as a webhook relay for inbound mail. That was wrong for Gmail specifically. Verified against Google's own support docs: Google retired **"Less Secure Apps"** (bare password, no 2FA) in 2022, but **App Passwords** (2-Step Verification > App passwords) remain fully supported for **both IMAP and SMTP**. The same App Password already used for outbound SMTP authenticates IMAP too (`imap.gmail.com:993`, SSL) — no OAuth2, no public tunnel, no Make.com needed. This does **not** apply to Microsoft 365/Outlook, which fully retired Basic Auth for mail protocols in Sept 2024 with no app-password equivalent — a webhook relay (Make.com or similar) is still the right call there.
- **IMAP polling revived (Make.com webhook removed):** `EmailWebhookResource`/`EmailWebhookSecretValidator` and `EMAIL_WEBHOOK_SECRET` are gone — `POST /api/v1/webhooks/email` now 404s. `EmailAdapter.scheduledPoll()`/`pollOnce()` connect via IMAP, parse each unseen message to `ChannelMessageReceived`, validate via `EventValidator`, publish on success (or count as an error on validation failure), and flag the message `SEEN`. `email.imap.user`/`password` default to the SMTP credential (`EMAIL_IMAP_USER:${EMAIL_SMTP_USER:}`) via `application.properties` nested-default syntax, so one Gmail App Password drives both directions with no extra config in the common case.
- **Inbound `Message-ID` is now captured end-to-end.** `EmailAdapter.parseMessage`/`extractMessageId` reads the inbound email's own `Message-ID` header and puts it on `ChannelMessageReceived.messageId` (a new field, with a backward-compatible constructor overload for older callers). Downstream it's persisted as `tickets.origin_message_id` (db-writer, migration `V7__ticket_origin_message_id.sql`), set once when the ticket stub is created.
- **Outbound replies thread into the original chain (RFC 5322).** `EmailAdapter.sendReply(...)` already accepted an `inReplyToMessageId` param (sets `In-Reply-To` + `References`), but every caller hard-coded `null`, so acks/updates/status-changes arrived as disconnected new emails. Now `EmailAdapterResource` (`/test-send`), `TicketsResource.reply()`, `TicketNotifier.sendStatusUpdate()`, and ai-core's `app/notifications/sender.py` all forward the stored `origin_message_id`, so every reply lands in the same email chain the citizen started. See the README's *Subject-line ticket threading & dedup* section.
- **Resend added as an alternate outbound provider (Render free-tier SMTP block).** Real Gmail SMTP sends from Render's free tier fail with `ConnectTimeoutException` after 60s — Render blocks outbound ports 25/465/587 on free web services entirely (as of 2025-09-26; a paid plan lifts the 465/587 block, 25 stays blocked everywhere since Render runs on AWS EC2 and AWS blocks 25 network-wide). `EmailAdapter.sendReply` now branches on `EMAIL_PROVIDER`: `smtp` (default, unchanged Quarkus-mailer path) or `resend` (`ResendEmailClient`, HTTPS to `api.resend.com`, port 443 is never blocked). Same `In-Reply-To`/`References` threading either way. ai-core's own timeout for calling api-gateway's `/test-send` (`services/ai-core/app/notifications/sender.py`) is now `EMAIL_SEND_TIMEOUT_SECONDS` (default 30s, was a hardcoded 10s) since a real SMTP/API round trip is slower than the mock path.
- **Thread-key collapse fix (ai-core side).** Complementary to threading: `ConversationAgent._thread_key()` no longer falls back to `email:<address>` (shared by every email from that sender, which collapsed unrelated new complaints onto old tickets) — it now uses `email:<message-id>` when there's no real `In-Reply-To`. WhatsApp's per-phone thread key is unchanged. Regression-tested in `services/ai-core/tests/test_thread_key.py`.
- **Outbound SMTP is real, not mock, by default** (Phase 1, config-only — `EmailAdapter.sendReply()`/`test-send` are unchanged Java code). `quarkus.mailer.mock` defaults to `${EMAIL_SMTP_MOCK:false}`. Verified working against Gmail SMTP (`smtp.gmail.com:587`, STARTTLS) using an account App Password (requires 2-Step Verification). One easy-to-miss requirement: `quarkus.mailer.auth-methods=PLAIN LOGIN` **must** be set explicitly — Gmail advertises XOAUTH2 first, and without this the mailer tries XOAUTH2 (no token available) instead of the App Password and every send fails. `EMAIL_FROM_ADDRESS` should match `EMAIL_SMTP_USER` (or a verified Gmail alias) or Gmail may reject/bounce the send.
- **`test-send` failures now surface their real cause instead of a bare 500 (Feature 17 live-testing fix).** `EmailAdapterResource.testSend()` previously let any exception from `emailAdapter.sendReply(...)` propagate to Quarkus's default handler, which converts ANY uncaught exception into a generic `500` with no detail — so when Resend's sandbox 403 (see above) fired, ai-core's caller only ever saw "Server error '500...'", forcing a cross-service log hunt (api-gateway's own logs had the real 403 + message the whole time). Now caught explicitly and returned as `502` with `{sent:false, error:<the real exception message>}`. Complementary fix on ai-core's side: `app/notifications/sender.py`'s `send_email`/`send_whatsapp` now log the upstream response body (`_error_body_snippet`) on failure, not just httpx's generic "Server error ..." string, so the real cause shows up in ai-core's own log line too, not only api-gateway's.
- **`inReplyTo` now also resolves a ticket directly (Feature 19, shared with WhatsApp).** `ensure_ticket_stub` (`app/tickets/intake.py`) now checks the inbound `In-Reply-To` header (already captured as `ChannelMessageReceived.inReplyTo`) against every ticket's own `origin_message_id` FIRST, ahead of the subject-line ticket-number check — an extra safety net for mail clients that strip the `[Ticket TKT-XXXXX]` tag from "Re:" subjects. The primary motivation was WhatsApp's swipe-reply (see `docs/02b_ADAPTER_WHATSAPP.md`), but the field and the match are channel-agnostic.
- **Auto-generated mail is dropped at ingestion (`EmailAdapter.isAutoGenerated`).** Bounces, out-of-office replies, and no-reply notification streams are detected via RFC 3834 `Auto-Submitted`, `X-Autoreply`/`X-Autorespond`/`X-Failed-Recipients`, `Precedence: bulk|junk|auto_reply`, DSN `multipart/report` content-types, null `Return-Path`, mailer-daemon/postmaster/*noreply* senders, and bounce/OOO subject patterns — marked SEEN and skipped (logged) before parsing, so they never become `channel.message.received` events. ai-core keeps a sender/subject safety net in `app/events/dispatcher.py` (`is_auto_generated_email`), and `app/notifications/sender.py` refuses to send to RFC 2606 reserved domains (`example.com` etc. — dev seed data), which closes the seed→bounce→ticket feedback loop that once filed a Gmail DSN as a confirmed complaint from mailer-daemon. Detection errs permissive: on any parsing doubt the mail goes through (a lost complaint is worse than a junk ticket). Unit-tested in `EmailAdapterParseTest` and ai-core's `tests/test_auto_response.py`.
