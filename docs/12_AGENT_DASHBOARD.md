# Feature 12 — Agent Dashboard

## Phase Scope
- **Phase 1:** Full implementation — all three tabs, RBAC, PWA
- **Phase 2:** Twitter alert banner on ticket queue for ministerial mentions

## What This Module Does
Next.js 14 PWA. Three tabs: Analytics, Ticket Queue, Administration.
Responsive — Next.js handles desktop (side-sheet detail) and mobile
(full-page navigation) automatically. Single codebase for all devices.

---

## PWA Configuration

```js
// next.config.js
const withPWA = require('next-pwa')({
  dest: 'public',
  register: true,
  skipWaiting: true,
  disable: process.env.NODE_ENV === 'development'
});
```

Service worker caches the shell. Works offline (shows cached ticket list).
Push notifications for new critical tickets (Phase 2: Twitter alerts).

---

## App Structure

```
apps/dashboard/
├── app/
│   ├── (auth)/
│   │   └── login/page.tsx
│   ├── (agent)/
│   │   ├── layout.tsx          ← tab navigation, role-gated
│   │   ├── analytics/page.tsx
│   │   ├── queue/
│   │   │   ├── page.tsx        ← Ticket Queue
│   │   │   └── [id]/page.tsx   ← Ticket Detail (mobile full-page)
│   │   └── admin/
│   │       └── page.tsx        ← Administration (admin only)
│   └── status/
│       └── [ref]/page.tsx      ← Citizen portal (SSR, public)
├── components/
│   ├── queue/
│   │   ├── TicketQueue.tsx     ← list + filters + sort
│   │   ├── TicketRow.tsx
│   │   ├── TicketDetail.tsx    ← side-sheet (desktop) / page (mobile)
│   │   ├── TicketFilters.tsx
│   │   ├── PreFilterBar.tsx    ← quick filter buttons
│   │   ├── NotesTimeline.tsx
│   │   ├── AddNote.tsx
│   │   ├── StatusTransition.tsx
│   │   └── ResolutionField.tsx
│   ├── analytics/
│   │   ├── VolumeChart.tsx
│   │   ├── SlaDonut.tsx
│   │   ├── PriorityBar.tsx
│   │   └── AgentTable.tsx
│   ├── admin/
│   │   ├── AgentList.tsx
│   │   ├── AddAgentForm.tsx
│   │   └── TenantConfig.tsx
│   └── ui/                     ← shadcn/ui components
├── lib/
│   ├── api.ts                  ← API client (calls api-gateway)
│   ├── auth.ts                 ← JWT handling
│   └── rbac.ts                 ← client-side role checks
└── store/
    ├── tickets.ts              ← Zustand
    └── auth.ts
```

---

## Tab 1 — Analytics (all roles, view-only)

### Content
- Ticket volume: line chart by day, last 30 days
- Volume by channel: stacked bar (email, WhatsApp)
- SLA performance: donut — met vs breached %
- Priority distribution: bar chart by label
- Agent performance table (Lead + Admin only):
  - Tickets resolved, avg handle time, SLA breach rate

### Component
```tsx
// analytics/page.tsx
export default function AnalyticsPage() {
  const { role } = useAuth();
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      <VolumeChart period="30d" />
      <SlaDonut period="30d" />
      <PriorityBar />
      {(role === 'admin' || role === 'lead') && <AgentTable />}
    </div>
  );
}
```

---

## Tab 2 — Ticket Queue

### Default Sort Order
Priority score descending → created_at ascending (oldest high-priority first).

### Role-based View
```tsx
const { role, agentId } = useAuth();
const assignedToFilter = role === 'agent' ? agentId : undefined;
// Agents see only their tickets. Lead/Admin see all.
```

### Pre-Filter Bar (quick one-click filters)

```tsx
// components/queue/PreFilterBar.tsx
const preFilters = [
  { label: 'My Tickets',  filter: { assignedTo: 'me' } },
  { label: 'All Open',    filter: { status: 'open,assigned,in_progress' } },
  { label: 'Overdue',     filter: { slaBreached: true } },
  { label: 'Unassigned',  filter: { assignedTo: 'none' } },
  { label: '🔴 Critical', filter: { priorityLabel: 'critical' } },
];
// Renders as pill buttons. One active at a time.
// PHASE_2: Add 'Twitter Alerts' filter for ministerial mention tickets
```

### Filter Panel (expandable)

Fields:
- Date range: created / last updated / resolved (date pickers)
- Status: multi-select checkboxes
  (Open, Assigned, In-Progress, Resolved, Reopened, Closed)
- Priority: multi-select (Critical, High, Medium, Low)
- Channel: multi-select (Email, WhatsApp)
- Assigned agent: dropdown (Lead/Admin only)
- Category: dropdown from tenant config
- Identity type: All / Confirmed / Anonymous / Pending

### Ticket Row

```tsx
// Each row shows:
// [Priority badge] [Ticket #] [Category] [Channel icon]
// [Customer name or ANON-XXXX] [Assignee] [Age] [SLA indicator]
// Click → opens TicketDetail (side-sheet desktop / navigate mobile)
```

### Ticket Detail — Layout

**Desktop:** Side-sheet slides in from right (60/40 split with list visible).
**Mobile:** Full-page navigation.

Next.js handles this with a responsive layout:
```tsx
// app/(agent)/queue/page.tsx
// Uses useMediaQuery to decide sheet vs page navigation
```

#### Detail — Left Panel (60%)

```
┌─────────────────────────────────────────┐
│ Ticket #TKT-00142  [high] [whatsapp]    │
│ Created: 27 Jun 2025  SLA: 6h remaining │
├─────────────────────────────────────────┤
│ Category: Billing / Incorrect Amount    │
│ Channel: WhatsApp                       │
│ Customer: Rajesh Kumar (+91 98765...)   │  ← PHASE_2: decrypted display
│           or  ANON-7X3K                 │
│ Assigned: Priya S (Agent)               │
│ Last updated: 2h ago                    │
├─────────────────────────────────────────┤
│ RESOLUTION                              │
│ ┌────────────────────────────────────┐  │
│ │ [editable when in_progress/resolved│  │
│ │  locked when closed]               │  │
│ │ [Generate Summary] button          │  │
│ └────────────────────────────────────┘  │
├─────────────────────────────────────────┤
│ NOTES & COMMENTS  (chronological)       │
│                                         │
│ 🤖 AI  •  27 Jun 09:15                 │
│ "Customer reports billing amount..."    │
│                                         │
│ ✉  User  •  27 Jun 09:22              │
│ "My bill is double since March"         │
│                                         │
│ 👤 Priya S (Agent)  •  27 Jun 10:00   │
│ "Checked meter reading records..."      │
│                                         │
│ ┌────────────────────────────────────┐  │
│ │ Add a note...                      │  │
│ │                           [Submit] │  │
│ └────────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

#### Detail — Right Panel (40%)

```
┌──────────────────────────┐
│ STATUS                   │
│ [In Progress ▾]          │  ← role-gated transitions
│                          │
│ PRIORITY (Lead/Admin)    │
│ [High ▾]                 │
│                          │
│ ASSIGNED TO (Lead/Admin) │
│ [Priya S ▾]              │
│                          │
│ [Save Changes]           │
├──────────────────────────┤
│ AUDIT TRAIL ▸ (expand)   │
│ 09:15 Ticket created     │
│ 09:22 Status: assigned   │
│ 10:00 Note added         │
└──────────────────────────┘
```

---

## Notes Timeline Component

```tsx
// components/queue/NotesTimeline.tsx
type NoteAuthorType = 'ai' | 'agent' | 'user' | 'system';

function NoteEntry({ note }: { note: TicketNote }) {
  const icons = {
    ai:     '🤖',
    agent:  '👤',
    user:   '✉️',
    system: '⚙️'
  };
  const colors = {
    ai:     'bg-teal-50 border-teal-200',
    agent:  'bg-slate-50 border-slate-200',
    user:   'bg-blue-50 border-blue-200',
    system: 'bg-gray-50 border-gray-200'
  };
  return (
    <div className={`rounded-lg border p-3 mb-2 ${colors[note.authorType]}`}>
      <div className="flex items-center gap-2 text-sm font-medium mb-1">
        <span>{icons[note.authorType]}</span>
        <span>{note.authorLabel}</span>
        <span className="text-gray-400 font-normal ml-auto">
          {formatRelative(note.createdAt)}
        </span>
      </div>
      <p className="text-sm text-gray-700">{note.content}</p>
    </div>
  );
}
```

---

## Add Note Component

```tsx
// components/queue/AddNote.tsx
function AddNote({ ticketId, onTransition }: Props) {
  const [content, setContent] = useState('');
  const minChars = 20; // for mandatory transitions

  const handleSubmit = async () => {
    if (content.trim().length < 1) return;
    await api.addNote(ticketId, content);
    setContent('');
  };

  return (
    <div className="border rounded-lg p-3 mt-4">
      <textarea
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder="Add a note..."
        className="w-full text-sm resize-none"
        rows={3}
      />
      <div className="flex justify-between items-center mt-2">
        <span className="text-xs text-gray-400">{content.length} chars</span>
        <Button onClick={handleSubmit} disabled={content.trim().length < 1}>
          Submit
        </Button>
      </div>
    </div>
  );
}
```

---

## Status Transition Component

```tsx
// components/queue/StatusTransition.tsx
// Shows allowed transitions based on current status + user role
// Enforces mandatory note (20 chars) for:
//   in_progress → resolved
//   resolved → closed
//   closed → reopened
// Shows note input inline when mandatory transition selected

const MANDATORY_NOTE_TRANSITIONS = [
  'in_progress->resolved',
  'resolved->closed',
  'closed->reopened'
];

function StatusTransition({ ticket, role }: Props) {
  const [targetStatus, setTargetStatus] = useState('');
  const [note, setNote] = useState('');
  const needsNote = MANDATORY_NOTE_TRANSITIONS.includes(
    `${ticket.status}->${targetStatus}`
  );
  const canSubmit = !needsNote || note.trim().length >= 20;

  // ...render status dropdown + conditional note textarea
}
```

---

## Resolution Field Component

```tsx
// components/queue/ResolutionField.tsx
function ResolutionField({ ticket, role }: Props) {
  const [summary, setSummary] = useState(ticket.resolution || '');
  const [generating, setGenerating] = useState(false);
  const [aiError, setAiError] = useState('');

  const isEditable = ['in_progress', 'resolved'].includes(ticket.status);
  const isLocked   = ticket.status === 'closed';

  const generateSummary = async () => {
    setGenerating(true);
    setAiError('');
    try {
      const result = await api.generateResolutionSummary(ticket.id);
      setSummary(result.summary);
    } catch (err) {
      // Graceful degradation when AI is down
      setAiError('AI summary unavailable. Please write resolution manually.');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="mt-4">
      <label className="text-sm font-semibold text-gray-600">Resolution</label>
      <textarea
        value={summary}
        onChange={e => setSummary(e.target.value)}
        disabled={!isEditable || isLocked}
        className={`w-full mt-1 text-sm border rounded p-2
          ${isLocked ? 'bg-gray-50 text-gray-500' : ''}`}
        rows={4}
        placeholder={isEditable ? 'Describe the resolution...' : ''}
      />
      {isEditable && (
        <div className="flex items-center gap-2 mt-1">
          <Button variant="outline" size="sm"
                  onClick={generateSummary} disabled={generating}>
            {generating ? 'Generating...' : 'Generate Summary'}
          </Button>
          {aiError && (
            <span className="text-xs text-red-500">{aiError}</span>
          )}
        </div>
      )}
    </div>
  );
}
```

---

## Tab 3 — Administration (Admin only)

### Agent Management
- Table: name, email, role badge, status (active/inactive), joined date
- Actions per row: Edit role, Deactivate, Reset password
- "Add Agent" button → inline form or modal
- Role change: dropdown (Admin, Lead, Agent)

### Tenant Configuration
- Category taxonomy editor (add/remove categories and subcategories)
- SLA rules per priority level
- Identity timeout (hours)
- Anonymous complaints toggle
- LLM provider selector

### System Health
- Pod status (api-gateway, ai-core, db-writer) — green/red indicators
- Valkey queue depth
- DB Writer cache hit rate
- Last backup timestamp

---

## Citizen Portal (Public — SSR)

```
/status/ANON-7X3K
/status?email=rajesh@example.com
```

No login required. Shows:
- Ticket number, status, last updated
- Category
- Next steps
- Contact information

```tsx
// app/status/[ref]/page.tsx
// Server-side rendered for accessibility + SEO
export async function generateMetadata({ params }) { ... }
export default async function StatusPage({ params }) {
  const ticket = await fetchTicketByRef(params.ref);
  if (!ticket) return notFound();
  return <CitizenStatusView ticket={ticket} />;
}
```

---

## Environment Variables

```env
NEXT_PUBLIC_API_URL=http://api-gateway:8080
NEXT_PUBLIC_WS_URL=ws://api-gateway:8080
NEXTAUTH_SECRET=...
NEXTAUTH_URL=http://localhost:3000
NEXT_PUBLIC_APP_ENV=development
```

---

## Test Stubs

```http
### Get ticket queue — Lead view (all tickets)
GET http://localhost:3000/api/tickets?sortBy=priority_score&sortDir=desc
Cookie: access_token={{lead_token}}

### Expected
HTTP/1.1 200 OK
{ "tickets": [...25 tickets...], "total": 25, "page": 1 }

### Get ticket queue — Agent view (own tickets only)
GET http://localhost:3000/api/tickets?assignedTo=me
Cookie: access_token={{agent_token}}

### Expected (agent has 8 assigned tickets)
HTTP/1.1 200 OK
{ "tickets": [...8 tickets...], "total": 8 }

### Apply pre-filter: Overdue
GET http://localhost:3000/api/tickets?slaBreached=true
Cookie: access_token={{lead_token}}

### Apply date range filter
GET http://localhost:3000/api/tickets?dateFrom=2025-06-01&dateTo=2025-06-27&status=open,assigned
Cookie: access_token={{lead_token}}

### Get ticket detail
GET http://localhost:3000/api/tickets/TKT-00001
Cookie: access_token={{agent_token}}

### Expected
HTTP/1.1 200 OK
{
  "id": "...",
  "ticketNumber": "TKT-00001",
  "status": "in_progress",
  "resolution": null,
  "notes": [
    { "authorType": "ai", "authorLabel": "UniServe AI", "content": "...", "createdAt": "..." },
    { "authorType": "user", "authorLabel": "Anonymous User", "content": "...", "createdAt": "..." },
    { "authorType": "agent", "authorLabel": "Priya S", "content": "...", "createdAt": "..." }
  ]
}

### Generate AI resolution summary
POST http://localhost:3000/api/tickets/TKT-00001/generate-resolution-summary
Cookie: access_token={{agent_token}}

### Expected (AI available)
HTTP/1.1 200 OK
{ "summary": "Customer reported incorrect billing for March 2025. Meter reading verified on site. Bill revised and resent to customer." }

### Expected (AI down)
HTTP/1.1 503 Service Unavailable
{ "error": { "code": "AI_UNAVAILABLE", "message": "AI summary unavailable. Please write resolution manually." } }

### Status transition — agent moves to resolved with note
POST http://localhost:3000/api/tickets/TKT-00001/transition
Content-Type: application/json
Cookie: access_token={{agent_token}}

{
  "toStatus": "resolved",
  "note": "Meter reading was verified and corrected. Bill has been revised and resent to the customer via email."
}

### Expected
HTTP/1.1 200 OK
{ "status": "resolved", "resolvedAt": "2025-06-27T..." }

### Status transition — note too short (should fail)
POST http://localhost:3000/api/tickets/TKT-00001/transition
Content-Type: application/json
Cookie: access_token={{agent_token}}

{ "toStatus": "resolved", "note": "Done." }

### Expected
HTTP/1.1 422 Unprocessable Entity
{ "error": { "code": "NOTE_TOO_SHORT", "message": "Note must be at least 20 characters" } }

### Reopen ticket — resolution field cleared
POST http://localhost:3000/api/tickets/TKT-00002/transition
Content-Type: application/json
Cookie: access_token={{lead_token}}

{
  "toStatus": "reopened",
  "note": "Customer replied that the issue recurred in April billing cycle as well."
}

### Expected
HTTP/1.1 200 OK
{ "status": "reopened", "resolution": null, "assignedTo": "same-agent-who-closed" }

### Citizen portal — anonymous lookup
GET http://localhost:3000/status/ANON-TEST

### Expected (SSR, no auth)
HTTP/1.1 200 OK
<!-- HTML page with ticket status, category, last updated -->

### Admin — add agent
POST http://localhost:3000/api/agents
Content-Type: application/json
Cookie: access_token={{admin_token}}

{ "name": "New Agent", "email": "new@tneb.demo", "role": "agent", "password": "NewPass@123" }

### Expected
HTTP/1.1 201 Created
{ "id": "uuid", "name": "New Agent", "role": "agent", "isActive": true }
```

---

## Mock Data in Dashboard

When `APP_ENV=development`, the seed data provides:
- **25 tickets** across all statuses (5 per status)
- **All priority levels** (5 critical, 8 high, 8 medium, 4 low)
- **Both channels** (13 email, 12 whatsapp)
- **Mixed identity** (20 confirmed, 3 anonymous, 2 pending)
- **Full notes timelines** on 10 tickets (AI + user + agent notes)
- **3 SLA breached tickets** (for Overdue pre-filter testing)
- **5 tickets with resolution** filled (for closed status testing)

---

## Testing
- Admin login → all 3 tabs visible
- Lead login → Analytics + Ticket Queue visible, no Administration tab
- Agent login → Analytics + Ticket Queue visible (own tickets only)
- Ticket Queue loads sorted by priority desc by default
- Pre-filter "Overdue" → shows 3 tickets
- Date range filter → filters correctly
- Note submit with 1 char → button stays enabled but API rejects mandatory transitions
- "Generate Summary" when AI down → error message shown, text area still editable
- Resolution field locked after ticket closed
- Reopen → resolution field cleared in UI
- Mobile view → detail opens as full page, not side-sheet
- Citizen portal `/status/ANON-TEST` → loads without authentication

---

## Phase 1 Implementation Notes (deviations & corrections)
- Next.js **API routes proxy to the api-gateway**, forwarding the `access_token` cookie as a Bearer token; a readable `role` cookie drives client-side tab gating.
- **UI is functional-minimal**: login, role-gated dashboard (Analytics / Ticket Queue / Administration), a queue table, and the public citizen portal. The full component set (side-sheet detail, charts, expandable filter panel) is scaffolded, not pixel-complete — the verified acceptance is the **HTTP stubs** (API routes + citizen portal SSR).
- Citizen portal `/status/[ref]` (SSR, public) reads from the gateway's public endpoint `GET /api/v1/public/status/{ref}` (ticket number, anon-ref, or email), returning non-PII ticket status.
- **Ticket Queue: Confirmed vs "Needs identity" scope toggle.** Admins and leads get a toggle on the Ticket Queue that switches the list between `?identityStatus=confirmed` (the main queue, default) and `?identityStatus=pending,anonymous` (stub tickets whose identity isn't resolved yet); an **Identity** column shows each ticket's identity status. A ticket moves from Needs-identity to Confirmed automatically the moment identity resolves (`intake.update_ticket_identity`, ai-core). Agents still see only `?assignedTo=me` with no toggle. Backend filtering already existed end-to-end (`TicketsResource.list` → db-writer `TicketService.list` comma-`IN` on `identityStatus`); this was the missing frontend surface.
- **Ticket Queue overhaul (columns, sort, pagination, refresh).** The queue now shows **Name / Email / Mobile** columns (citizen fields joined from the identity profile), **Created**, and an **Identity** badge. Column headers are **server-side sortable** (`?sortBy=&sortDir=`; default `createdAt desc` = newest first) — including the citizen columns, which is why `db-writer`'s `TicketService.list` was moved to a native SQL query that LEFT JOINs `identity_profiles` (Panache active-record queries can't join on the free-text `identity_id`). **Pagination**: `?page=&pageSize=` (default 30, options 30/50/100) with Prev/Next + total-count nav above the table; the list response now returns the FULL matching `total` (db-writer runs a companion `COUNT(*)`), not the page size. The queue **auto-refreshes every 30s** (interval cleared on unmount), has a **manual Refresh** button, and persists `{scope, page, pageSize, sortBy, sortDir}` in `sessionStorage` (`uniserve.ticketQueue`) — so returning from a ticket-detail page refreshes and restores the same scope/page/sort. `sortBy` is whitelisted in db-writer (never interpolated raw) so it stays injection-safe.
- **UI_REVAMP_v2 phase 1 (additive-first).** The dashboard gained the §A3 chrome shell — sticky topbar (`src/components/layout/Topbar.tsx`: teal wordmark, announcement bell with unread badge/mark-all-read, role pill, logout via the new `POST /api/auth/logout` BFF route) and a collapsible sidebar (`Sidebar.tsx`, w-56/w-14, bottom tab bar ≤768px) driving the SAME tab-state union the old top tab bar did; a per-session-dismissible announcement banner renders under the topbar. The login page is a split layout: navy brand panel with the **BBC Tamil RSS headlines widget** (`/api/news` parses the feed server-side — free, no key, `NEWS_RSS_URL` overridable, hides silently on failure) and the public announcement ticker (`GET /api/public/announcements`, titles only, no auth); the sign-in form logic is unchanged. Brand palette centralised in `src/lib/design-tokens.ts`. The full page-by-page visual reskin (spec §A5–A7) is deliberately deferred to a later phase.
- **Administration → Announcements** (`AnnouncementsPanel.tsx`): tenant notices CRUD — active list + collapsible expired/inactive, create/edit modal (title ≤80 / body ≤500 with counters, optional expiry date stored as end-of-day, active toggle). Backend: `announcements` table (V8), db-writer `/api/v1/db/announcements`, gateway `/api/v1/announcements` (view = all roles, manage = admin; RBAC actions `announcements.view`/`announcements.manage`; path added to `AuthFilter.isProtected`).
- **Administration → System** (`SystemPanel.tsx`): service-health dots (server-side `/api/system/health` probe, 30s auto + manual refresh) and the **danger-zone tenant DB reset** — non-dismissible modal, current password + literal `RESET` required, button disabled until both valid; 401/429/generic error handling; success redirects to login. Backend: gateway `POST /api/v1/admin/reset` (admin role via `admin.system.reset`, bcrypt password re-verification) → db-writer `POST /api/v1/db/admin/reset` (60s per-tenant rate limit, tenant-scoped deletes preserving the tenants row + calling admin, `tenant.reset` audit event with per-table counts written inside the same transaction after the deletes, ticket cache flushed).
- **Fixed: Service Health always showed all three services "Unreachable" on Vercel.** `/api/system/health` (`apps/dashboard/src/app/api/system/health/route.ts`) hardcoded `http://localhost:8080/8090/8001` for api-gateway/db-writer/ai-core — correct for Docker/local-dev, but there's no localhost to reach from a Vercel serverless function. Base URLs are now configurable: api-gateway reuses `API_GATEWAY_INTERNAL_URL`/`NEXT_PUBLIC_API_GATEWAY_URL` (same vars `gatewayBase()` already reads), and two new dashboard env vars, `DB_WRITER_URL` and `AI_CORE_URL`, point at db-writer's (Railway) and ai-core's (Render) real URLs — all three default to their old `localhost:PORT` values, so local/Docker dev is unaffected. The displayed port is now derived from whichever URL is actually configured (443 for a bare `https://` host) instead of a hardcoded number, so it doesn't show a stale `:8080` next to a real HTTPS check.
- **Ticket detail layout v2 (user-requested).** Two equal columns. LEFT = reference: Conversation (own scroll) above Audit trail (own scroll, **newest first**). RIGHT = action: citizen details; a **Status & internal note** panel — one note textarea (grey "Add internal note" placeholder) plus one button per allowed next status, the note travels with the transition (no separate "Add note" button; a small "Save note only" link remains for notes without a status change); **"Ask a follow-up / update the customer"** with a **Send** button that shows a busy spinner then an explicit ✓ sent / ✗ FAILED confirmation (incl. network-error handling) so agents always know whether the citizen actually got the message; internal-notes history below.
- **New status: `pending_customer`** ("pending customer" badge, purple). `in_progress ⇄ pending_customer` and `pending_customer → resolved`; any role may park a ticket (`ticket.status.to_pending_customer`). Schema via V9 (tickets CHECK rebuild). The follow-up panel hints agents to park the ticket after asking a question.
- **Ticket detail: Audit trail section.** A scrollable section at the bottom of the detail page's left column lists the ticket's lifecycle — created, assignments (`ticket.assigned`/`unassigned`, recorded by db-writer whenever `assignedTo` changes, with the acting agent from the gateway's `actorAgentId`), and status transitions — each with actor name and timestamp. Backed by `GET /api/v1/tickets/{id}/events` (gateway resolves agent ids to names) over the existing `ticket_events` table.
- **Intake Fields: admin-defined custom fields.** "Add field" on the Intake Fields panel creates a tenant-defined field (label, free-text or numeric validation, optional exact digits; key auto-derived from the label). Saved via `PUT /api/v1/tenant/intake-fields/catalog` into `intakeFieldCatalog`; ai-core's `catalog_for_tenant()` merges customs into the runtime catalog with generic extractors/validators, so the new field cascades to the bot with no code change. Custom rows show a ✕ to remove (which also strips the key from all channel configs).
- **Settings: login-page news feed URL.** `generalSettings.newsFeedUrl` (validated http(s)) is editable in Administration → Settings; the public `GET /api/v1/public/news-config` serves it to the dashboard's `/api/news` route, which prefers it over the `NEWS_RSS_URL` env and the BBC Tamil default. Blank restores the default.
- **Administration sub-tabs added: Priority Rules and Settings.** `PriorityRulesPanel.tsx` edits the tenant's free-text AI priority rubric (`GET|PUT /api/v1/tenant/priority-rubric`, pre-filled with the backend's default writeup of the current scoring engine); `GeneralSettingsPanel.tsx` edits tenant general settings — currently `maxFollowupQuestions` 0–5 (`GET|PUT /api/v1/tenant/general-settings`). Both proxy through Next.js routes under `src/app/api/tenant/` and are admin-only (enforced at the gateway via `admin.tenant.config`). See the README's *Configurable priority rubric & general settings* section.
- **Administration → Landing Page** (`LandingPagePanel.tsx`): every string on the public `/` page, plus the logo, the five palette colours, the About/How-it-works/Contact cards, up to 10 extra sections, and the footer note + links. Saves the whole object to `GET|PUT /api/v1/tenant/landing-page` (`LandingPageResource`, `admin.tenant.config`, merging only the `landingPage` key of `config_json`); the page itself reads the same content unauthenticated via `GET /api/v1/public/landing-page` (`PublicLandingPageResource`), which returns built-in defaults with `200` on any failure. **Blank means "use the default"** — `LandingPageContent.resolve` lays stored values over defaults field by field, the panel shows each default as a placeholder, and it repaints from the resolved response after a save. Colours are restricted to `#RGB`/`#RRGGBB` and logo/link URLs to `/path`, `http(s)` and (links only) `mailto:`/`tel:`, on **read as well as write**, because that content reaches `style`/`src`/`href` on an unauthenticated page and `TenantConfigResource` can write the blob without passing through this validator. See the README's *Configurable landing page* section.
- **Landing page is now a server component.** `src/app/page.tsx` fetches tenant content server-side (ISR, `revalidate = 60`) so the copy is in the initial HTML — no flash of default wording, and indexable. Only the lookup form (`src/components/landing/TrackComplaintForm.tsx`) ships JS. `src/lib/landingPage.ts` holds the types, the client-side default mirror and `coerceLandingPage`; the server-side read is split into `landingPage.server.ts` because `lib/gateway` imports `next/headers`, which cannot be bundled for the browser.

## Chief complaint column & header (Feature 23)

The queue's columns all described a complaint the agent could not actually
read — number, status, priority, category, channel, citizen, assignee — so
triage meant opening tickets one at a time. `tickets.chief_complaint` (V12,
derived by ai-core; see the README's *Chief complaint* section) is now surfaced
in both screens:

- **Queue**: a **Chief complaint** column immediately after the ticket number,
  where a subject line belongs. Capped at `max-w-[20rem]` and `truncate`d with
  the full text on `title` hover — one line per ticket keeps the table
  scannable. Server-side sortable via `sortBy=chiefComplaint` (whitelisted in
  `TicketService.SORT_COLUMNS`), which groups identical complaint text
  together — the cheapest duplicate-spotter available.
- **Ticket detail**: rendered directly under the `TKT-…` heading rather than
  among the metadata fields, since it is the ticket's subject line and an agent
  should not have to hunt for it. Rendered even when empty ("Not yet
  determined") so the page never silently omits it — a blank one means the
  citizen's first message hasn't been processed yet, which is itself worth
  seeing.

`GET /api/v1/tickets/{id}` returns it as `chiefComplaint`; the queue list
carries the raw `chief_complaint` column.

## Full-detail CSV export (Feature 23)

**Export CSV** on the queue toolbar now downloads every field the ticket-detail
page shows plus the three timelines — `conversation`, `internal_notes`,
`audit_trail` — one multi-line cell each, still **one row per ticket**. The
previous export was the queue column-for-column, which meant the export of a
complaint-handling system contained no complaint text, no citizen name, and no
record of who did what.

The button sends no `detail` param (full is the gateway's default);
`?detail=summary` returns the old flat shape. Because the transcripts cost three
extra db-writer calls per ticket, the full export caps at **2,000 rows** where
the flat one caps at 50,000 — the confirmation line reports the row count and,
when capped, the cap itself, from `X-Export-Row-Count` / `X-Export-Row-Cap` /
`X-Export-Detail` (all forwarded by the dashboard's export proxy route).

## Possible-duplicate banner (Feature 22)

When routing cannot tell whether a new message continues an existing complaint
(`match_open_ticket` -> `unclear`), it creates the ticket and records a
`ticket.possible_duplicate` event on it, carrying the other ticket's id/number
in `meta_json`. The AI asks the citizen in the conversation, but citizens
often never answer — so the ticket page shows an amber banner until an agent
settles it.

`outstandingDuplicate(events)` derives the state from the audit trail: a
`possible_duplicate` counts as outstanding only while no later
`duplicate_confirmed` / `duplicate_dismissed` follows it. There is no extra
ticket column and no polling — the page already fetches its own audit trail.

**Yes, merge** / **No, separate** post to
`POST /api/v1/tickets/{id}/duplicate` (`ticket.edit`, i.e. admin/lead), which
applies the identical `isDuplicate`/`parentTicketId`/closed treatment the
conversation path uses and writes both audit trails. The citizen answering in
the conversation and an agent clicking here are the same decision, taken by
whichever gets there first.

## Unrouted messages & newest-first conversation (Feature 24)

**Conversation is newest-first**, matching the audit trail beside it — an agent
opening a ticket wants the latest exchange, not to scroll a long thread to reach
it. Reversed in the component, not server-side: chronological is the correct
storage order and the CSV export reads it that way.

**Unrouted** is a new sidebar view (`UnroutedPanel.tsx`), **lead/admin only** —
gated in the sidebar AND again in `dashboard/page.tsx`, because the active tab
key persists in `sessionStorage` and a demoted lead must not land on a view they
can no longer use.

It lists citizen messages routing declined to attribute to any ticket and
declined to invent one for (see the README's *Inbound routing ladder*).
`pending` means the citizen has been asked for a ticket number; `escalated`
means they were asked once already and the next message was also unroutable, so
the bot stopped asking. Each row shows the message, the sender, and why routing
gave up.

Two actions. **Attach** takes the ticket **number** the agent is reading (the
gateway resolves it to an id) and copies the text onto that ticket's
conversation — clearing the queue without delivering the message would defeat
the point of storing it. **Discard** marks it noise. The row is kept either way.

BFF routes: `/api/unrouted-messages`, `/api/unrouted-messages/[id]/attach`,
`/api/unrouted-messages/[id]/discard` — thin pass-throughs so a 403 from the
gateway's RBAC reaches the UI intact.

**If the tab shows an error instead of a queue**, read it: the panel renders
`error.message` from the gateway verbatim, and the two it is most likely to show
both name the cause.

- *"The data service does not have GET /api/v1/db/unrouted-messages (HTTP 404)…"*
  — db-writer is deployed behind api-gateway. Redeploy db-writer from current
  `main`; see the README's *Deploy db-writer before (or with) api-gateway*. This
  view is the first place that drift shows, because it is the only screen reading
  an endpoint nothing else calls — the rest of the dashboard looks fine.
- *"…answered … with HTTP 5xx and a body that is not JSON…"* — db-writer is down,
  restarting, or still waking, and a platform error page came back instead of
  data. Retry once the service is up.

Neither should ever appear as raw parser text again. An HTML response used to
reach the panel as Jackson's `Unexpected character ('<' (code 60))…`, which named
nothing useful; `DbWriterClient` now turns an unparseable body into a named error
(`DbWriterNonJsonResponseTest`, `UnroutedMessagesResourceTest`).

An empty queue is **not** an error — it renders "Nothing unrouted — every recent
message reached a ticket." Seeing that on a healthy stack means routing attributed
everything, which is the intended steady state.

**A reply on a resolved ticket is not visually flagged** (the user's explicit
choice: "audit only, add to conversation"). It appears at the top of the
conversation and as a `ticket.reply_after_resolution` line in the audit trail;
the ticket's status is untouched.


## Ticket ETA in the agent UI (Feature 26)

The **Status & internal note** panel gained an ETA date picker, because that is
where the value is actually captured: an ETA is mandatory the first time a
ticket moves, and db-writer refuses the transition with `422 ETA_REQUIRED`
otherwise.

- Transition buttons carry an **"ETA required"** badge and stay disabled until a
  date is set, alongside the existing "Note required" treatment. The client
  check mirrors the server rule; the server still enforces it, and its 422
  message is surfaced verbatim rather than swallowed - otherwise an agent would
  be staring at a button that silently does nothing.
- The rule keys on `firstTransitionAt` being null, **not** on `status`, so the
  server decides. A ticket whose status was changed by the unvalidated PATCH
  path (how ai-core closes a confirmed duplicate) has still never been picked up
  by an agent, and must still be asked for an ETA.
- **Cancel is exempt** and shows no badge.
- An **"Update ETA only"** button appears once an ETA exists, for the ordinary
  revisions (the part arrived early, the crew got pulled to an outage) -
  `PATCH /api/v1/tickets/{id}/eta`, audited server-side as `ticket.eta_changed`.
- The ETA is also in the header field row next to Category/Priority/Channel,
  reading "not set" in amber when absent, because an agent on the phone needs it
  without scrolling to the transition box.
- The date input's `min` is today in the browser's timezone; the server
  independently rejects past dates.

## Administration - WhatsApp Menu (Feature 26)

A seventh admin sub-tab (`WhatsAppMenuPanel.tsx`) editing every string a citizen
reads on WhatsApp, grouped in the order the conversation actually runs -
welcome and menu, option 1 (existing ticket), option 2 (new ticket), duplicates,
ending the chat - plus the `enabled` toggle and the session length.

Same conventions as the Landing Page panel, both load-bearing: **blank means
"use the default"** (a blank welcome would otherwise send an empty WhatsApp
message), and the server's RESOLVED view is echoed back after a save so a
cleared field visibly refills with its default rather than looking as though it
saved empty. Placeholder names (`{company}`, `{ticket}`, `{status}`, `{eta}`,
`{updated}`, `{existing}`, `{question}`) are listed inline per field.
