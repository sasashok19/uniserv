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
- Citizen portal `/status/[ref]` (SSR, public) reads from the gateway's public endpoint `GET /api/v1/public/status/{ref}` (anon-ref or email), returning non-PII ticket status.
- **Ticket Queue: Confirmed vs "Needs identity" scope toggle.** Admins and leads get a toggle on the Ticket Queue that switches the list between `?identityStatus=confirmed` (the main queue, default) and `?identityStatus=pending,anonymous` (stub tickets whose identity isn't resolved yet); an **Identity** column shows each ticket's identity status. A ticket moves from Needs-identity to Confirmed automatically the moment identity resolves (`intake.update_ticket_identity`, ai-core). Agents still see only `?assignedTo=me` with no toggle. Backend filtering already existed end-to-end (`TicketsResource.list` → db-writer `TicketService.list` comma-`IN` on `identityStatus`); this was the missing frontend surface.
- **Ticket Queue overhaul (columns, sort, pagination, refresh).** The queue now shows **Name / Email / Mobile** columns (citizen fields joined from the identity profile), **Created**, and an **Identity** badge. Column headers are **server-side sortable** (`?sortBy=&sortDir=`; default `createdAt desc` = newest first) — including the citizen columns, which is why `db-writer`'s `TicketService.list` was moved to a native SQL query that LEFT JOINs `identity_profiles` (Panache active-record queries can't join on the free-text `identity_id`). **Pagination**: `?page=&pageSize=` (default 30, options 30/50/100) with Prev/Next + total-count nav above the table; the list response now returns the FULL matching `total` (db-writer runs a companion `COUNT(*)`), not the page size. The queue **auto-refreshes every 30s** (interval cleared on unmount), has a **manual Refresh** button, and persists `{scope, page, pageSize, sortBy, sortDir}` in `sessionStorage` (`uniserve.ticketQueue`) — so returning from a ticket-detail page refreshes and restores the same scope/page/sort. `sortBy` is whitelisted in db-writer (never interpolated raw) so it stays injection-safe.
- **UI_REVAMP_v2 phase 1 (additive-first).** The dashboard gained the §A3 chrome shell — sticky topbar (`src/components/layout/Topbar.tsx`: teal wordmark, announcement bell with unread badge/mark-all-read, role pill, logout via the new `POST /api/auth/logout` BFF route) and a collapsible sidebar (`Sidebar.tsx`, w-56/w-14, bottom tab bar ≤768px) driving the SAME tab-state union the old top tab bar did; a per-session-dismissible announcement banner renders under the topbar. The login page is a split layout: navy brand panel with the **BBC Tamil RSS headlines widget** (`/api/news` parses the feed server-side — free, no key, `NEWS_RSS_URL` overridable, hides silently on failure) and the public announcement ticker (`GET /api/public/announcements`, titles only, no auth); the sign-in form logic is unchanged. Brand palette centralised in `src/lib/design-tokens.ts`. The full page-by-page visual reskin (spec §A5–A7) is deliberately deferred to a later phase.
- **Administration → Announcements** (`AnnouncementsPanel.tsx`): tenant notices CRUD — active list + collapsible expired/inactive, create/edit modal (title ≤80 / body ≤500 with counters, optional expiry date stored as end-of-day, active toggle). Backend: `announcements` table (V8), db-writer `/api/v1/db/announcements`, gateway `/api/v1/announcements` (view = all roles, manage = admin; RBAC actions `announcements.view`/`announcements.manage`; path added to `AuthFilter.isProtected`).
- **Administration → System** (`SystemPanel.tsx`): service-health dots (server-side `/api/system/health` probe, 30s auto + manual refresh) and the **danger-zone tenant DB reset** — non-dismissible modal, current password + literal `RESET` required, button disabled until both valid; 401/429/generic error handling; success redirects to login. Backend: gateway `POST /api/v1/admin/reset` (admin role via `admin.system.reset`, bcrypt password re-verification) → db-writer `POST /api/v1/db/admin/reset` (60s per-tenant rate limit, tenant-scoped deletes preserving the tenants row + calling admin, `tenant.reset` audit event with per-table counts written inside the same transaction after the deletes, ticket cache flushed).
- **Ticket detail: Audit trail section.** A scrollable section at the bottom of the detail page's left column lists the ticket's lifecycle — created, assignments (`ticket.assigned`/`unassigned`, recorded by db-writer whenever `assignedTo` changes, with the acting agent from the gateway's `actorAgentId`), and status transitions — each with actor name and timestamp. Backed by `GET /api/v1/tickets/{id}/events` (gateway resolves agent ids to names) over the existing `ticket_events` table.
- **Intake Fields: admin-defined custom fields.** "Add field" on the Intake Fields panel creates a tenant-defined field (label, free-text or numeric validation, optional exact digits; key auto-derived from the label). Saved via `PUT /api/v1/tenant/intake-fields/catalog` into `intakeFieldCatalog`; ai-core's `catalog_for_tenant()` merges customs into the runtime catalog with generic extractors/validators, so the new field cascades to the bot with no code change. Custom rows show a ✕ to remove (which also strips the key from all channel configs).
- **Settings: login-page news feed URL.** `generalSettings.newsFeedUrl` (validated http(s)) is editable in Administration → Settings; the public `GET /api/v1/public/news-config` serves it to the dashboard's `/api/news` route, which prefers it over the `NEWS_RSS_URL` env and the BBC Tamil default. Blank restores the default.
- **Administration sub-tabs added: Priority Rules and Settings.** `PriorityRulesPanel.tsx` edits the tenant's free-text AI priority rubric (`GET|PUT /api/v1/tenant/priority-rubric`, pre-filled with the backend's default writeup of the current scoring engine); `GeneralSettingsPanel.tsx` edits tenant general settings — currently `maxFollowupQuestions` 0–5 (`GET|PUT /api/v1/tenant/general-settings`). Both proxy through Next.js routes under `src/app/api/tenant/` and are admin-only (enforced at the gateway via `admin.tenant.config`). See the README's *Configurable priority rubric & general settings* section.
