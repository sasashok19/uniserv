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
| interactive list reply | → extract row title as rawText (Feature 29 sends these) |

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
- **Swipe-reply ticket matching (Feature 19).** A citizen's swipe-reply to a
  specific WhatsApp message carries Meta's `context.id` (the quoted
  message's wamid) in the webhook payload — `WhatsAppParser` has always
  captured this as `inReplyTo` on the `ChannelMessageReceived` event, but
  it went unused for inbound ticket routing until now (only outbound reply
  threading consumed it). ai-core's `ensure_ticket_stub`
  (`app/tickets/intake.py`) now checks it FIRST: if `inReplyTo` matches a
  ticket's own `origin_message_id`, that ticket is used directly — the most
  explicit continuation signal a citizen can give, ahead of an explicit
  `TKT-XXXXX` mention in the text or the identity/same-topic heuristic. See
  the README's "Subject-line ticket threading & dedup" section for the
  live-tested bug this fixes (a swipe-reply follow-up with no topical
  overlap to its parent message was creating a duplicate ticket).
- **Intake answers stay on the same ticket (Feature 20).** WhatsApp's
  identity gate is a multi-message exchange, and the citizen's reply to it
  ("Nithya", "nithya@gmail.com", "56784567") describes no problem at all —
  so the Feature 18 same-topic check, asked whether it continues the open
  complaint, said "no" and each reply became its own ticket (live-tested:
  `+918939014142` → TKT-00016, TKT-00017, TKT-00018 for one complaint).
  ai-core's `ensure_ticket_stub` now routes a message that is purely
  intake-form data (`looks_like_intake_answer`, deterministic — no LLM) to
  the citizen's one still-in-intake stub, before any topic reasoning. This
  is channel-agnostic code but WhatsApp-only in effect: email never reaches
  the identity/open-count branch, since it has subject-line matching. See
  the README's "Intake answers are not new complaints" section.
- **Conversation menu (Feature 26).** WhatsApp is no longer a free-text-only
  channel: ai-core's `app/conversation/menu.py` runs a deterministic state
  machine in front of everything else on this channel. The AI sends the first
  message (a welcome naming the tenant's configured company, plus options
  1/2/3), `#` returns to the main menu from anywhere, and every message except
  the goodbye carries that hint. Options 1 (status/ETA/last-updated for one
  named ticket, then an optional note) and 3 (goodbye) are answered entirely by
  the menu and **create no ticket**, so it runs BEFORE `ensure_ticket_stub`.
  Only option 2 falls through to the existing intake + routing ladder.
  Session state lives in Valkey at `wamenu:{tenantId}:whatsapp:<phone>` with a
  tenant-configurable TTL (default 12h, hard-capped at 24h — see the
  customer-service window above; a session that outlived it could never be
  answered). Copy is per-tenant under `config_json.whatsappMenu`
  (`GET|PUT /api/v1/tenant/whatsapp-menu`, admin only) and can be switched off
  entirely with `whatsappMenu.enabled = false`, which restores the previous
  behaviour exactly. Full write-up: the README's "WhatsApp conversation menu".
  - **Interactive button replies matter here.** As documented above, a button
    reply arrives as the button's *title*, not its number, so the option matcher
    accepts `1`/`1.`/`1)`/`one`/`status` and a leading word from a button title
    — otherwise buttons would be inert.
  - **Deliberate consequence for rungs 0-1.** With no live session, a
    swipe-reply (`context.id`) or a typed `TKT-00042` now receives the welcome
    menu rather than routing straight to its ticket. This is what the strict
    menu means and is the documented trade-off; `whatsappMenu.enabled` is the
    escape hatch.
  - **Ownership is checked** before any ticket's status is read out. Ticket
    numbers are sequential and guessable, so a ticket belonging to someone else
    is reported exactly like one that does not exist.
  - Tests: `services/ai-core/tests/test_whatsapp_menu.py` (35),
    `test_menu_content.py` (11, including a guard that parses
    `WhatsAppMenuContent.java` and fails if the Java and Python default copy
    ever drift), plus the menu cases in `test_dispatcher.py`.
- **Interactive reply buttons (Feature 28).** `WhatsAppAdapter.sendReply` gained
  a `buttons`/`footer` overload that emits Meta's `type: "interactive"` /
  `interactive.type: "button"` payload, and
  `POST /api/v1/internal/adapters/whatsapp/send` accepts `buttons` (up to 3
  `{id, title}`) and `footer`. Omitting both sends plain text exactly as before,
  so every pre-existing caller is unchanged.
  - Meta's caps are enforced by **truncation** in `buildPayload` (3 buttons,
    20-char title, 1024-char body, 60-char footer) because exceeding any of them
    makes Meta reject the entire message — the citizen would receive nothing.
  - A button set that comes out empty falls back to a text payload; Meta rejects
    a button message with no buttons.
  - Interactive messages are **not templates**, so the 24-hour customer-service
    window above applies to them unchanged.
  - The menu now uses this, which finally makes the parser's long-standing
    `button_reply` branch reachable. A tap arrives as the button's **title**, so
    ai-core matches taps against the tenant's configured labels.
  - `WhatsAppInteractiveTest` covers the payload shape and every cap.
- **Interactive list messages (Feature 29).** Three buttons could not carry a
  four-option main menu or a citizen's ticket list, so `buildPayload` gained
  Meta's second interactive shape, `interactive.type: "list"`: one section, up
  to 10 rows of `{id, title, description}`, opened by a labelled strip.
  - **The caller does not choose the shape — `WhatsAppAdapter.needsList` does.**
    Reply-buttons stay the default because the choices sit in the thread instead
    of behind a tap. A list is used only when buttons cannot express the ask:
    more than 3 options, or any option carrying a `description` (a button has no
    second line, and dropping it would silently lose the detail that tells one
    ticket from another).
  - This **replaces Feature 28's truncation** of surplus buttons. Clipping to
    three was survivable when the menu had exactly three options; it would now
    mean the citizen never sees "End chat".
  - New caps, same truncate-don't-trust rule: 10 rows, 24-char row title,
    72-char row description, 200-char row id, 20-char list button label
    (defaulting to `Choose`). Body and footer caps are shared with buttons.
  - **Row ids are forced unique.** Meta rejects the whole send on a duplicate,
    and two rows collide easily once an id defaults to a title that is then
    clipped to 24 characters (`TKT-00042 · Power cut in Madambakkam` and
    `... in Selaiyur` are the same 24 characters).
  - `POST /api/v1/internal/adapters/whatsapp/send` keeps the field name
    `buttons` for wire compatibility and adds an optional `listLabel`. Entries
    may now carry `description`.
  - A row set that comes out empty falls back to text, exactly as buttons do.
  - The 72-char description is what gives a ticket row room to name its
    complaint alongside `TKT-00042` in a 24-char title.
  - `WhatsAppListMessageTest` covers shape selection, every cap, id uniqueness
    and the parser reading back a tapped row.
- **The conversation the list messages carry (Feature 29).** Four main-menu
  options (update my details / ticket status / new ticket / end chat), the
  citizen greeted by name when the number resolves to an identity, their tickets
  listed as tappable rows instead of asked for by number, a **Main menu** option
  on every message below the top level, and one message — not two — to close out
  a registration. The flow, its states and every config key are documented in
  the README's *WhatsApp conversation menu* section.
  - **No text-box-with-Submit.** WhatsApp has no inline form outside a published
    **Flow**, which is a Meta-console asset rather than something in this repo.
    The name/email/complaint steps therefore ask and take the citizen's next
    message as the answer, with the Main menu option as the cancel. Converting a
    step to a Flow later is contained: the state machine does not care where the
    text came from.
- **Answering us is not starting a chat (Feature 28).** A citizen replying to an
  agent's follow-up used to get the welcome menu, losing their answer: the
  agent's message goes out through the gateway, so ai-core never saw it and no
  menu session existed. `menu.awaiting_our_reply` now checks for a swipe-reply to
  one of our messages, or a recent unanswered outbound on one of their tickets,
  and hands those straight to the routing ladder.
  - Checked in TWO places. "No session" is the obvious one; the one that
    actually fires is the idle `MENU` state, because a citizen who used the menu
    earlier still has a session for up to 12h and their answer matches no
    option. A chosen option still wins over it, and a match clears the session
    so the agent's conversation is not interrupted again next turn.
  - **Only a human agent's message counts as "awaiting".** Accepting any
    outbound trapped citizens behind the assistant's own replies — every later
    message bypassed the menu into the routing ladder, which parked it as
    unrouted and then went silent. `author_type` must be `agent`; `ai` and
    `system` are not questions we are waiting on.
  - **A chosen option is never treated as an answer.** The option match runs
    first in both places. Without that ordering an outstanding agent question
    made every message from that citizen bypass the menu — including their menu
    keypresses, which is how a citizen ended up unable to open a new ticket at
    all (live: "3", then a "New ticket" tap, then their complaint, all filed onto
    TKT-00014).
  - **Option 2 suppresses routing rung 2 AND guarantees a ticket.** Pressing
    "register a new ticket" is a statement that this is not a reply, so
    `ensure_ticket_stub` is called with `explicit_new_complaint=True`. Rungs 0/1
    and the rung-4 duplicate check are unaffected. The flag also counts as a new
    complaint at rung 4 — suppressing rung 2 on its own dropped a clarification
    ("No it is for a different area") into the unrouted queue with no reply.
  - **A dead end offers the menu instead of silence.** When rung 5 escalates and
    sends no ask, the dispatcher re-sends the main menu and resets the session
    to `MENU`. The citizen's words are already stored for a lead; what was
    missing was a way forward.
  - `nothing is awaiting this citizen's reply ... rejected=[...]` is logged with
    a per-ticket reason (`citizen-spoke-last`, `outside-reply-window`,
    `intake-question`), alongside a `whatsapp menu inbound ... state=... option=...`
    line — diagnosing this from the outside otherwise means reading the code
    against a Valkey dump.
- **Ask before creating a duplicate (Feature 26).** An ambiguous repeat
  complaint now asks the citizen a distinguishing question and creates nothing
  until they answer (`app/dedup/confirmation.py`, state at
  `dupconfirm:{tenantId}:{threadKey}`). Confirmed-same attaches the message to
  the existing ticket rather than creating and merging a second row. See the
  README's "Asking before creating a duplicate".
