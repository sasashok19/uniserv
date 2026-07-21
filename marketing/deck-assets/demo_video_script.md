# UniServe Live Demo — Narration Script & Storyboard

Recorded live against the running application (localhost, admin/lead/agent
roles, tenant `t1`). The citizen side of every "email"/"WhatsApp" complaint is
simulated through ai-core's real conversation-agent endpoint
(`POST /api/v1/internal/process-test-event`) rather than a literal Gmail
round-trip — same AI/identity/ticket code path the live IMAP/WhatsApp adapters
feed, just without needing a second party's mailbox credentials. Everything
else (ticket queue, ticket detail, admin console, analytics) is the real
dashboard UI, screen-recorded.

Voice: Microsoft Ravi (Windows offline TTS, Indian English, male).

---

### Scene 1 — Cold open
**Narration:** "This is UniServe — an AI-powered complaint platform. Everything you're about to see is running live, right now, on the actual product. Nothing here is a mockup. Let's watch it meet someone for the very first time."
**On screen:** Login page (news ticker, announcements).

### Scene 2 — The queue, before
**Narration:** "Sign in as an administrator, and open the ticket queue. Right now there is no ticket yet for our new complainant — digiaim underscore group1 at IIM Cal dot ac dot in."
**On screen:** Admin signs in → Ticket Queue tab, current ticket count visible.

### Scene 3 — Complaint #1, turn 1 (no info given)
**Narration:** "Digiaim just emails in a complaint — but gives no name, no mobile number, no consumer ID. Watch how the assistant responds."
**On screen:** Trigger the AI conversation turn; overlay card shows the assistant's own response: identity pending, one follow-up question asked, ticket not yet filed.

### Scene 4 — The queue still holds the line
**Narration:** "Back in the queue — still nothing filed. UniServe won't create an incomplete ticket. It holds the line and asks for what it actually needs, first."
**On screen:** Refresh Ticket Queue — ticket count unchanged.

### Scene 5 — Complaint #1, turn 2 (details given)
**Narration:** "Digiaim replies with their name, mobile number, and consumer ID. Now watch the assistant complete the picture."
**On screen:** Trigger the second turn; overlay card: identity confirmed, complaint ready, category and priority scored.

### Scene 6 — The ticket appears, fully formed
**Narration:** "And there it is — a brand-new ticket, already categorized, already prioritized, identity already confirmed — all before a human agent lifted a finger."
**On screen:** Refresh queue → new ticket at top → open its detail page → Citizen Details panel (mobile populated, category, priority).

### Scene 7 — Complaint #2, a different channel entirely
**Narration:** "Now here's the real test. The same person contacts us again — this time on WhatsApp, about something completely unrelated: a billing question. And this time they give us nothing but their phone number."
**On screen:** Trigger a WhatsApp-channel complaint using the same phone number, no name, no email. Overlay card: identity confirmed instantly, zero follow-up questions.

### Scene 8 — The payoff: identity linked across channels
**Narration:** "Open that ticket, and look at the citizen details. Email address — already filled in. Nobody typed it on WhatsApp. UniServe recognized the same phone number from the first complaint, and pulled the rest of the profile across automatically. One citizen. One identity. Every channel."
**On screen:** Open the new WhatsApp ticket's detail page → Citizen Details panel, email field visible and populated.

### Scene 9 — Admin cascade, part 1
**Narration:** "One more thing worth seeing. Everything the assistant asks for is tenant configuration, not code. Watch what happens when an admin adds a brand-new required field, live."
**On screen:** Administration → Intake Fields. Add/enable a new mandatory field ("Connection Type") on the Email channel; save; panel reflects the change.

### Scene 10 — Admin cascade, part 2
**Narration:** "A fresh complaint comes in right after — and the assistant is already asking about Connection Type, a field that didn't exist a minute ago. No redeploy. No code change."
**On screen:** Trigger a third, brand-new-identity complaint on the email channel; overlay card shows the pending/follow-up state reflecting the new field.

### Scene 11 — Agent workflow and the audit trail
**Narration:** "Once a ticket exists, it flows into the normal workspace. A lead assigns it, an agent works it — and every step, assignment, transition, note, is captured in an audit trail nobody can quietly skip."
**On screen:** Lead assigns the WhatsApp billing ticket to an agent; agent transitions it to in-progress, replies, then resolves with a mandatory note. Ticket detail shows the growing audit trail.

### Scene 12 — Zoom out and close
**Narration:** "Zoom out, and the operational picture updates in real time — volume, priority mix, SLA view. That's UniServe: one AI front door, one identity per citizen, a fully governed ticket, every single time."
**On screen:** Analytics tab, charts visible; end card.

---

## If recording without a voice-over
Read each scene's narration aloud (or have a narrator read it) while performing
the "on screen" action described — the pacing above (roughly 12–20 seconds per
scene) is a reasonable dwell time per screen. Total run time: approximately
4–5 minutes.
