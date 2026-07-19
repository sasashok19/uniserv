# UI_REVAMP_v2.md — Implementation Brief for Claude CLI
# Version 2 — Updated to reflect README as of latest commit

## How to use this file
```bash
claude "Read UI_REVAMP_v2.md fully before writing any code.
Implement exactly what is described, section by section.
Confirm with me before starting each major section.
Do not modify backend business logic — UI and new features only."
```

Spawn parallel sub-agents where marked **[PARALLEL]**.
Confirm with the user at every **[CONFIRM]** checkpoint.

---

## Project Context — Read This First

UniServe is a multi-tenant AI-powered complaint portal.

**Stack:**
- `apps/dashboard/` — Next.js 14, port 3000
- `services/api-gateway/` — Quarkus Java, port 8080
- `services/db-writer/` — Quarkus Java, port 8090 (NOT 8081)
- `services/ai-core/` — Python FastAPI, port 8001
- SQLite WAL, Valkey event bus

**Critical gotchas from README — read before touching anything:**
1. `AuthFilter.isProtected()` hardcodes path prefixes. Any new
   RBAC-protected route MUST be added there or gets silent NPE.
2. `TicketCache.java` hardcodes 1000 entries / 2-min TTL —
   env vars `DB_WRITER_CACHE_MAX_SIZE`/`_TTL_MINUTES` are not read.
3. `IntakeFieldsResource.java` (Java) and `intake_fields.py` (Python)
   share a field catalog that must be kept in sync manually.
4. `TENANT_ID` must be `t1` (not `default`) for dev seed logins to work.
5. `IdentityService.merge()` uses primary key, not `master_id` —
   do not trigger automatic merges until this is fixed.
6. db-writer port is **8090**, not 8081 (some older docs say 8081).

**Auth:** Custom JWT cookie. No NextAuth.
`app/api/auth/login/route.ts` proxies to api-gateway.

**RBAC:** admin / lead / agent enforced in api-gateway.

---

## STOP — Read existing code first **[CONFIRM #1]**

Before writing any code:
1. List every file in `apps/dashboard/src/` or `apps/dashboard/app/`
2. List every existing component, route, and BFF handler
3. Read `docs/12_AGENT_DASHBOARD.md`
4. Read `docs/11_MULTI_TENANCY.md`
5. Read `docs/05_TICKET_SCHEMA.md`
6. Read `src/lib/badges.ts` (existing colour palette)

Present a summary of what exists. Wait for "proceed".

---

## What Is Already Built (do not duplicate)

Based on the README, the following is already functional:

### Already-built dashboard components
- `src/app/page.tsx` — landing page
- `src/app/login/page.tsx` — agent login
- `src/app/dashboard/page.tsx` — role-gated dashboard
  with Analytics / Ticket Queue / Administration tabs
- `src/components/analytics/AnalyticsPanel.tsx` — recharts:
  volume (stacked bar), SLA (donut), priority (bar), agents (bar)
  with filter bar: timeframe, agent, customer typeahead,
  priority, category
- `src/components/admin/TeamPanel.tsx` — agent list + add/edit
- `src/components/admin/IntakeFieldsPanel.tsx` — per-channel
  intake field matrix (mandatory/optional/native)
- `src/components/admin/PriorityRulesPanel.tsx` — free-text
  AI priority rubric editor
- `src/components/admin/GeneralSettingsPanel.tsx` — maxFollowupQuestions
- `src/app/dashboard/tickets/[id]/page.tsx` — 2-column ticket
  detail (citizen details + status transition left;
  conversation timeline right)
- `src/app/status/[ref]/page.tsx` — public citizen status lookup
- `src/lib/badges.ts` — shared colour palette

### Already-built Ticket Queue features
- Confirmed vs "Needs identity" scope toggle (admin/lead)
- Identity column, Name/Email/Mobile columns
- Server-side sortable column headers
- Pagination (30/50/100 per page, Prev/Next, total count)
- Auto-refresh every 30 seconds
- Manual Refresh button
- sessionStorage view state persistence
- Agents see only their own assigned tickets

### Already-built Admin tabs
- Team (agent management)
- Intake Fields
- Priority Rules
- Settings (maxFollowupQuestions)

### Already-built API BFF routes
- auth, agents, tenant, tickets, analytics (all standard routes)
- `POST /api/tickets/[id]/reply` — send update to citizen
- `POST /api/tickets/archive-stale`
- `GET|PUT /api/tenant/intake-fields`
- `GET|PUT /api/tenant/priority-rubric`
- `GET|PUT /api/tenant/general-settings`
- `GET /api/analytics/agents-directory`
- `GET /api/analytics/customers?q=`

---

## Scope of This Implementation

### IN SCOPE
- Complete UI/UX visual revamp (design tokens, layout, all pages)
- News widget on landing/login page (geolocation-based)
- Admin announcements (new Admin sub-tab + display for all users)
- Admin DB reset (password-protected, in System sub-tab)
- New backend endpoints: announcements CRUD, DB reset
- New schema: announcements table (Flyway V8+)
- Update docs/12_AGENT_DASHBOARD.md
- Update docs/05_TICKET_SCHEMA.md
- Update README.md

### OUT OF SCOPE — DO NOT TOUCH
- AI pipeline, event bus, identity resolution logic
- Authentication / JWT handling
- Ticket business logic, status transitions, RBAC rules
- Intake fields, priority rubric, general settings panels
  (already built — only reskin visually)
- Any Phase 2 features
- ai-core service

---

## FEATURE A — Design System & Layout Revamp **[PARALLEL Track 1]**

### Step A1 — Design tokens

Create `apps/dashboard/src/lib/design-tokens.ts`:

```typescript
export const tokens = {
  colors: {
    navy:       '#0D1B2A',
    navyMid:    '#1B3A52',
    teal:       '#028090',
    tealLight:  '#02C39A',
    tealXL:     '#E8F6F8',
    gold:       '#F4A261',
    goldLight:  '#FFF3E8',
    coral:      '#E07B54',
    coralLight: '#FFF0EB',
    white:      '#FFFFFF',
    offWhite:   '#F8FAFC',
    slate:      '#F1F5F9',
    border:     '#E2E8F0',
    grey:       '#64748B',
    black:      '#0F172A',
    success:    '#1A936F',
    warning:    '#F59E0B',
    danger:     '#DC2626',
    info:       '#0284C7',
  },
  priority: {
    critical: { bg:'#FEF2F2', text:'#DC2626', border:'#FECACA', dot:'#DC2626' },
    high:     { bg:'#FFF7ED', text:'#EA580C', border:'#FED7AA', dot:'#EA580C' },
    medium:   { bg:'#FEFCE8', text:'#CA8A04', border:'#FEF08A', dot:'#CA8A04' },
    low:      { bg:'#F0FDF4', text:'#16A34A', border:'#BBF7D0', dot:'#16A34A' },
  },
  status: {
    open:        { bg:'#EFF6FF', text:'#1D4ED8', label:'Open' },
    assigned:    { bg:'#F5F3FF', text:'#7C3AED', label:'Assigned' },
    in_progress: { bg:'#FFF7ED', text:'#C2410C', label:'In Progress' },
    resolved:    { bg:'#F0FDF4', text:'#15803D', label:'Resolved' },
    closed:      { bg:'#F8FAFC', text:'#475569', label:'Closed' },
    reopened:    { bg:'#FFF1F2', text:'#BE123C', label:'Reopened' },
  },
  channel: {
    email:    { color:'#0284C7', icon:'Mail'          },
    whatsapp: { color:'#16A34A', icon:'MessageCircle' },
  },
  identityStatus: {
    confirmed:  { bg:'#F0FDF4', text:'#15803D', label:'Confirmed'     },
    pending:    { bg:'#FFF7ED', text:'#C2410C', label:'Needs identity' },
    anonymous:  { bg:'#F5F3FF', text:'#7C3AED', label:'Anonymous'     },
  }
}
```

Update `src/lib/badges.ts` to import and re-export from
design-tokens — do not duplicate values.

### Step A2 — Dependencies

```bash
cd apps/dashboard
npm install framer-motion lucide-react
# shadcn/ui components:
npx shadcn-ui@latest add button input label card badge
npx shadcn-ui@latest add dialog sheet select calendar
npx shadcn-ui@latest add tabs toast skeleton separator
npx shadcn-ui@latest add dropdown-menu popover tooltip
npx shadcn-ui@latest add scroll-area avatar
```

Note: `recharts` is already installed (used by AnalyticsPanel).

### Step A3 — Global layout shell

Replace/update `app/(agent)/layout.tsx` or equivalent
layout wrapper with:

**Topbar** (fixed, full-width, h-14):
- Left: UniServe SVG wordmark (teal gradient) + tenant name
- Centre: Announcement bell (see Feature C) with unread badge
- Right: Avatar (initials, coloured circle) + name + role pill
  (Admin=navy, Lead=teal, Agent=slate) + logout button

**Sidebar** (left, collapsible, w-56 expanded / w-14 collapsed):
- Chevron toggle button at bottom
- CSS transition 200ms ease
- Nav items: Analytics, Ticket Queue, Administration (admin only)
- Active: teal left border 3px + teal text + teal icon
- Hover: slate-100 background
- All icons from lucide-react
- Mobile (≤768px): sidebar becomes bottom tab bar (4 items max)

**Main content area**: scrollable, takes remaining space.

### Step A4 — Login page revamp

Replace `src/app/login/page.tsx` with split layout:

Left panel (40%, navy bg):
- UniServe logo + tagline "The complaint that gets heard."
- Animated stat counters (fetch from analytics, or use
  placeholder values if API not available):
  - Tickets resolved today
  - Average response time
  - SLA met %
- News widget (Feature B) below stats
- Announcement ticker (Feature C) at bottom of panel

Right panel (60%, white):
- Card centred vertically
- Email + password fields (shadcn Input)
- "Sign in" button (teal gradient background)
- Error state: red border + inline message
- Loading state: spinner in button, fields disabled

### Step A5 — Analytics tab revamp

**Keep all existing chart logic and API calls.**
Only update visual presentation:

- Hero stats row: 4 gradient cards with count-up animation
  (use `useEffect` + `useState` counter, increment every 16ms)
  Cards: Total tickets (navy), Open (teal), Resolved today (green),
  SLA met % (gold)
- Charts: already recharts — add teal gradient fill to AreaChart
  if not present, ensure hover tooltips styled consistently
- Filter bar: already exists — wrap in collapsible panel,
  "Filters" button toggles open/close with animation

### Step A6 — Ticket Queue revamp

**Keep ALL existing logic** (scope toggle, columns, sort,
pagination, auto-refresh, sessionStorage). Only update visuals:

Pre-filter buttons (pill style, one active at a time):
```
[My Tickets] [All Open] [🔴 Critical] [Overdue] [Unassigned]
[Confirmed ▾] [Needs identity ▾]   ← existing scope toggle, restyled
```

Table rows:
- Priority dot (8px circle, colour from tokens.priority)
- Status badge (colour from tokens.status)
- Identity status badge (colour from tokens.identityStatus)
- Channel icon (Mail/MessageCircle with channel colour)
- SLA indicator: green clock / amber if <2h / red if breached
- Hover: row shadow lift
- Alternating row backgrounds (white / offWhite)

### Step A7 — Ticket detail revamp

**Keep existing 2-column layout and all logic.**
Only update visuals:

Left column:
- Citizen details card: avatar initials + name/anon-ref,
  email, phone, service_id — card with teal left border
- Status transition: styled select + mandatory note textarea
  (20-char minimum enforced, char counter shown)
- Internal Notes: card per note, agent avatar, timestamp
- "Write an update": textarea + Send button, teal

Right column (conversation timeline):
- `max-h-[80vh] overflow-y-auto` (already exists — keep)
- Message cards: AI (teal left border, robot icon),
  User (blue left border, person icon),
  Agent (slate left border, agent avatar)
- Each card: author + timestamp + content

Resolution field:
- Shown when status in_progress or resolved
- Locked (read-only, grey bg) when closed
- "Generate Summary" button: teal outline, spinner on click
- Error state: "AI summary unavailable. Please write manually."
  — field stays editable

### Step A8 — Admin tab revamp

**Keep all 4 existing sub-tabs (Team, Intake Fields, Priority
Rules, Settings). Add 2 new sub-tabs (Announcements, System).**

Reskin existing sub-tabs visually (cards, proper spacing,
consistent badge styles) without changing any logic.

Add tabs "Announcements" and "System" — see Features C and D.

### Step A9 — Toast & empty states

Install and configure toast (shadcn/ui):
- Success: green (tokens.success)
- Error: coral (tokens.coral)
- Info: teal (tokens.teal)
- Position: bottom-right

Empty states per context:
- Ticket Queue empty: inbox illustration + "No tickets found"
- Analytics no data: chart placeholder + "No data for this period"
- Admin team empty: "No agents yet" + Add button

Skeleton loaders for all data-fetching components
(replace any spinners that show while data loads).

---

## FEATURE B — News Widget (Geolocation) **[PARALLEL Track 2]**

### What it does
On login page left panel: shows local news headlines.
Requests browser geolocation. Silent graceful degradation.

### New BFF route

`apps/dashboard/src/app/api/news/route.ts`:

```typescript
// GET /api/news?country=in
// Server-side — NEWS_API_KEY never exposed to browser
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const country = searchParams.get('country') || 'in';
  const NEWS_API_KEY = process.env.NEWS_API_KEY;

  if (!NEWS_API_KEY) {
    return Response.json({ articles: [] });
  }
  try {
    const url = `https://newsapi.org/v2/top-headlines` +
      `?country=${country}&pageSize=4&apiKey=${NEWS_API_KEY}`;
    const res  = await fetch(url, { next: { revalidate: 1800 } });
    const data = await res.json();
    return Response.json({ articles: data.articles || [] });
  } catch {
    return Response.json({ articles: [] });
  }
}
```

### Client component

`apps/dashboard/src/components/news/NewsWidget.tsx`:

States (in order):
1. `idle` → call `navigator.geolocation.getCurrentPosition()`
2. `locating` → "Detecting your location..."
3. `loading` → skeleton (3 card placeholders)
4. `success` → news cards (horizontal scroll mobile, grid desktop)
5. `error` / `denied` → hide entirely (no error shown to user)

Reverse geocode (no key needed):
```
https://api.bigdatacloud.net/data/reverse-geocode-client
  ?latitude={lat}&longitude={lon}&localityLanguage=en
```
Extract `countryCode` → pass to `/api/news?country={code}`.

Card design:
```
┌────────────────────────────────┐
│ Source name · 2h ago           │
│ Headline truncated to 2 lines  │
└────────────────────────────────┘
```
Click → open article in new tab.

Placement: below stat counters in login left panel.
Title: Globe icon + "Local Headlines".

**Env var to add to `.env.local.example`:**
```
NEWS_API_KEY=   # NewsAPI.org key; leave empty to hide widget
```

**Graceful degradation rules (all must hold):**
- No `NEWS_API_KEY` → widget hidden, no error
- Geolocation denied → widget hidden, no error
- API error → widget hidden, no error
- Never blocks page load (async, renders after mount)

---

## FEATURE C — Admin Announcements **[PARALLEL Track 2]**

### Schema change **[CONFIRM #2 before applying]**

Show the migration SQL to the user and wait for confirmation.

New Flyway migration — use the next available version number
after V7 (check `services/db-writer/src/main/resources/db/migration/`
for the highest existing V number, then add 1):

```sql
-- VN__announcements.sql
CREATE TABLE IF NOT EXISTS announcements (
  id          TEXT PRIMARY KEY
                   DEFAULT (lower(hex(randomblob(16)))),
  tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  title       TEXT NOT NULL CHECK(length(trim(title)) >= 3),
  body        TEXT NOT NULL CHECK(length(trim(body)) >= 10),
  created_by  TEXT NOT NULL REFERENCES agents(id),
  is_active   INTEGER NOT NULL DEFAULT 1,
  expires_at  TEXT,              -- ISO 8601, NULL = never expires
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_announcements_tenant_active
  ON announcements(tenant_id, is_active, expires_at);
```

### db-writer endpoints

New resource class:
`services/db-writer/src/main/java/com/uniserve/resources/AnnouncementResource.java`

```
GET    /api/v1/db/announcements
       ?tenantId=&activeOnly=true|false
       → list, sorted created_at DESC
       (filter: expires_at IS NULL OR expires_at > datetime('now'))

POST   /api/v1/db/announcements
       body: { tenantId, title, body, createdBy, expiresAt? }
       → 201 with full announcement object

PATCH  /api/v1/db/announcements/{id}
       body: { title?, body?, isActive?, expiresAt? }
       → 200 with updated object

DELETE /api/v1/db/announcements/{id}?tenantId=
       → 204
```

### api-gateway routes

New resource:
`services/api-gateway/src/main/java/com/uniserve/resources/AnnouncementGatewayResource.java`

```
GET    /api/v1/announcements          → any authenticated user
POST   /api/v1/announcements          → admin only
PATCH  /api/v1/announcements/{id}     → admin only
DELETE /api/v1/announcements/{id}     → admin only

GET    /api/v1/public/announcements   → NO auth (login page ticker)
       Returns only { id, title } for active non-expired announcements
```

**CRITICAL:** Add `/api/v1/announcements` to
`AuthFilter.isProtected()` in api-gateway. The public endpoint
`/api/v1/public/announcements` goes in the unauthenticated
allowlist alongside `/api/v1/public/status/`.

RBAC actions to add to `RbacPolicy`:
- `announcements.view` → all roles
- `announcements.manage` → admin only

### Next.js BFF routes

```
src/app/api/announcements/route.ts          → GET / POST
src/app/api/announcements/[id]/route.ts     → PATCH / DELETE
src/app/api/public/announcements/route.ts   → GET (no auth)
```

### Dashboard — Admin Announcements sub-tab

New tab in Administration: **"Announcements"**
(insert between Settings and System tabs).

```
┌────────────────────────────────────────────────────┐
│ Announcements                          [+ New]      │
├────────────────────────────────────────────────────┤
│ Active (N)                                          │
│                                                     │
│ ┌──────────────────────────────────────────────┐   │
│ │ 🟢  System Maintenance Tonight               │   │
│ │     All services down 11pm–1am               │   │
│ │     Expires: 27 Jun 2025  · by Admin User    │   │
│ │     [Edit] [Deactivate] [Delete]             │   │
│ └──────────────────────────────────────────────┘   │
│                                                     │
│ ▸ Expired / Inactive (N) — click to expand         │
└────────────────────────────────────────────────────┘
```

Create/Edit modal (shadcn Dialog):
- Title field (max 80 chars + char counter)
- Body textarea (max 500 chars + char counter)
- Expiry date picker (shadcn Calendar, optional)
- Active toggle (shadcn Switch)
- Save / Cancel

### Dashboard — Announcement display (all authenticated users)

**Topbar bell** (`src/components/announcements/AnnouncementBell.tsx`):
- Fetches `/api/announcements?activeOnly=true` on mount
- Polls every 5 minutes
- Badge: count of announcements with
  `created_at > localStorage('announcementLastSeen')`
- Click → slide-down panel (last 3 active, most recent first)
- Panel "Mark all read" sets localStorage timestamp

**Announcement banner** (`src/components/announcements/AnnouncementBanner.tsx`):
- Most recent active announcement as dismissible bar
  below topbar (teal bg, white text, X button)
- Dismissed state in sessionStorage (reappears next login)
- Hidden if no active announcements

**Login page ticker** (`src/components/announcements/AnnouncementTicker.tsx`):
- Fetches `/api/public/announcements` (no auth)
- CSS marquee animation, left-to-right, pauses on hover
- Hidden if no active announcements

---

## FEATURE D — Admin DB Reset **[PARALLEL Track 2]**

### Security design
- Admin role only (RBAC enforced in api-gateway)
- Admin must re-enter their current password
- Admin must type "RESET" exactly in confirmation field
- Rate-limited: once per 60 seconds per tenant
- Audit log entry written BEFORE reset executes
- Admin's own account preserved after reset

### db-writer endpoint **[CONFIRM #3 before implementing]**

Show the delete sequence to the user and wait for confirmation.

New method in existing or new Admin resource class:

```
POST /api/v1/db/admin/reset
Headers: X-Internal-Key (required), X-Reset-Confirmation: RESET
Body: { tenantId }

Responses:
  200 → { message: "Reset complete", adminEmail }
  400 → { error: "CONFIRMATION_REQUIRED" }
  429 → { error: "RATE_LIMITED", retryAfterSeconds: 60 }
```

Delete sequence (within one transaction, tenant-scoped):
```sql
-- 1. Write audit log entry FIRST
INSERT INTO ticket_events ...

-- 2. Delete in dependency order
DELETE FROM ticket_events      WHERE tenant_id = ?;
DELETE FROM ticket_notes       WHERE tenant_id = ?;
DELETE FROM ticket_messages    WHERE tenant_id = ?;
DELETE FROM tickets            WHERE tenant_id = ?;
DELETE FROM identity_profiles  WHERE tenant_id = ?;
DELETE FROM identity_pending_queue WHERE tenant_id = ?;
DELETE FROM announcements      WHERE tenant_id = ?;

-- 3. Delete non-admin agents
DELETE FROM agents
  WHERE tenant_id = ? AND id != <calling_admin_id>;

-- 4. Keep: tenants row, calling admin's agents row
-- 5. Invalidate entire Caffeine cache
```

Rate limit implementation: Caffeine cache in db-writer,
key = `{tenantId}:reset`, value = timestamp, TTL 60s.

### api-gateway route

New resource or method:
`POST /api/v1/admin/reset`

Steps in api-gateway:
1. Verify `CurrentUser.role() == "admin"`
2. Fetch calling admin's agent record from db-writer
3. Verify submitted password against stored bcrypt hash
   (use same BCrypt library already used for login)
4. If password wrong → 401 with `{ error: "INVALID_PASSWORD" }`
5. Forward to `POST /api/v1/db/admin/reset` with
   `X-Reset-Confirmation: RESET` header

**CRITICAL:** Add `/api/v1/admin` to `AuthFilter.isProtected()`.

### Next.js BFF route

`src/app/api/admin/reset/route.ts`

POST body from UI:
```json
{ "password": "admin current password", "confirmation": "RESET" }
```

### Dashboard — System sub-tab (Admin only)

New "System" sub-tab in Administration (last tab).

```
┌────────────────────────────────────────────────────────┐
│ System                                                   │
├────────────────────────────────────────────────────────┤
│ Service Health                                           │
│ ● api-gateway  :8080  🟢 Healthy                        │
│ ● db-writer    :8090  🟢 Healthy                        │
│ ● ai-core      :8001  🟢 Healthy                        │
│ [Refresh]                                               │
├────────────────────────────────────────────────────────┤
│ ⚠️  Danger Zone                                         │
│ ─────────────────────────────────────────────────────  │
│ Reset Database                                          │
│ Permanently deletes all tickets, identities, notes,    │
│ and announcements. Your admin account is preserved.    │
│ This action cannot be undone.                          │
│                                                        │
│ [ Reset Database ]  ← coral outlined button            │
└────────────────────────────────────────────────────────┘
```

Service health: fetch each health endpoint, show
green/amber/red dot. 30-second auto-refresh.

**Reset modal** (shadcn Dialog, not dismissible by
clicking outside — `onInteractOutside={(e) => e.preventDefault()}`):

```
┌────────────────────────────────────────────────┐
│ 🔴 Reset Database                              │
│ ──────────────────────────────────────────────│
│ This will permanently delete all data.         │
│ Your admin account will be preserved.          │
│                                                │
│ Enter your password:                           │
│ [password field]                               │
│                                                │
│ Type RESET to confirm:                         │
│ [text field — must equal "RESET" exactly]      │
│                                                │
│ [ Cancel ]   [ Reset Everything ]             │
│               ↑ disabled until both valid      │
└────────────────────────────────────────────────┘
```

"Reset Everything" button:
- Disabled until password non-empty AND
  confirmation field === "RESET" exactly (case-sensitive)
- On click: spinner in button, all fields disabled
- On 200: green toast "Database reset. Redirecting..."
  then `router.push('/login')` after 1.5s
- On 401: "Incorrect password" inline error, fields re-enable
- On 429: "Please wait 60 seconds before trying again"
- On other error: "Something went wrong. Please try again."

---

## Implementation Order

Run Tracks 1 and 2 in parallel once **[CONFIRM #1]** is done.

```
[CONFIRM #1] Read existing code → present summary → wait

Track 1 (UI revamp) — can start immediately after CONFIRM #1:
  A1  Design tokens
  A2  Install dependencies
  A3  Layout shell (topbar + sidebar)
  A4  Login page
  A5  Analytics revamp (visual only)
  A6  Ticket Queue revamp (visual only)
  A7  Ticket detail revamp (visual only)
  A8  Admin tab revamp + new sub-tab placeholders
  A9  Toast + empty states + skeletons
  ✓   Test: all existing features still work

Track 2 (new features) — start after CONFIRM #1:
  [CONFIRM #2] Show announcements migration SQL → wait
  C1  Run Flyway migration (announcements table)
  C2  db-writer AnnouncementResource
  C3  api-gateway AnnouncementGatewayResource + AuthFilter
  C4  Next.js BFF routes for announcements
  C5  AnnouncementBell, AnnouncementBanner, AnnouncementTicker
  C6  Admin Announcements sub-tab UI
  B1  /api/news BFF route
  B2  NewsWidget component
  [CONFIRM #3] Show DB reset delete sequence → wait
  D1  db-writer reset endpoint
  D2  api-gateway reset route + AuthFilter
  D3  Next.js BFF reset route
  D4  Admin System sub-tab UI (health + danger zone)

Track 3 (docs — after both tracks done):
  Update docs/12_AGENT_DASHBOARD.md
  Update docs/05_TICKET_SCHEMA.md
  Update README.md (Dashboard section, env vars, phase roadmap)
```

---

## Files to Create (new)

```
apps/dashboard/src/
├── lib/design-tokens.ts
├── components/
│   ├── layout/
│   │   ├── Topbar.tsx
│   │   └── Sidebar.tsx
│   ├── announcements/
│   │   ├── AnnouncementBell.tsx
│   │   ├── AnnouncementBanner.tsx
│   │   ├── AnnouncementPanel.tsx
│   │   └── AnnouncementTicker.tsx
│   └── news/
│       └── NewsWidget.tsx
└── app/api/
    ├── news/route.ts
    ├── announcements/
    │   ├── route.ts
    │   └── [id]/route.ts
    ├── public/
    │   └── announcements/route.ts
    └── admin/
        └── reset/route.ts

services/db-writer/src/main/
├── resources/db/migration/VN__announcements.sql
└── java/com/uniserve/resources/
    ├── AnnouncementResource.java
    └── AdminResource.java (or add to existing)

services/api-gateway/src/main/java/com/uniserve/resources/
├── AnnouncementGatewayResource.java
└── AdminGatewayResource.java (or add to existing)
```

## Files to Modify (existing)

```
apps/dashboard/src/
├── lib/badges.ts                    → import from design-tokens
├── app/(agent)/layout.tsx           → new layout shell
├── app/login/page.tsx               → split layout revamp
├── app/dashboard/page.tsx           → tab additions
├── components/analytics/            → visual revamp only
├── components/admin/                → visual revamp + new tabs
├── app/dashboard/tickets/[id]/      → visual revamp only
└── .env.local.example               → add NEWS_API_KEY

services/api-gateway/src/main/java/com/uniserve/
└── auth/AuthFilter.java             → add /api/v1/announcements,
                                       /api/v1/admin to isProtected()

docs/
├── 12_AGENT_DASHBOARD.md
├── 05_TICKET_SCHEMA.md
└── README.md (root)
```

---

## Testing Checklist

Run through every item after implementation. Report results.

### Existing features (must still work)
- [ ] Login with admin@tneb.demo / Admin@123
- [ ] Ticket Queue loads (Confirmed + Needs identity tabs)
- [ ] Scope toggle (Confirmed / Needs identity) works
- [ ] Sorting by column works
- [ ] Pagination (30/50/100) works
- [ ] Auto-refresh every 30s
- [ ] sessionStorage state persists across ticket-detail nav
- [ ] Analytics charts load (all 4)
- [ ] Analytics filter bar works
- [ ] Ticket detail: both columns visible
- [ ] Status transition + mandatory note (20 chars)
- [ ] Generate Summary: spinner + result
- [ ] Generate Summary: error state (field still editable)
- [ ] Admin → Team: add/edit agent
- [ ] Admin → Intake Fields: save works
- [ ] Admin → Priority Rules: save works
- [ ] Admin → Settings: maxFollowupQuestions saves
- [ ] Public status page: /status/ANON-XXXX loads

### UI revamp
- [ ] Sidebar collapses to icons
- [ ] Mobile: bottom tab bar appears at ≤768px
- [ ] Topbar: logo, avatar, role pill visible
- [ ] Priority dots: correct colour per priority
- [ ] Status badges: correct colour per status
- [ ] Identity status badges: correct colour
- [ ] Skeleton loaders appear during data fetch
- [ ] Toast: success (green), error (coral), info (teal)
- [ ] Empty state shown when ticket queue empty
- [ ] Login page: split layout, both panels visible
- [ ] Count-up animation on Analytics hero stats

### News widget
- [ ] Geolocation prompt appears on login page
- [ ] Articles load after permission granted
- [ ] Widget hidden (no error shown) when denied
- [ ] Widget hidden when NEWS_API_KEY not set

### Announcements
- [ ] Admin creates announcement → appears in list
- [ ] Bell badge shows count
- [ ] Banner shows most recent active announcement
- [ ] Dismiss banner → hidden for session
- [ ] Expired announcement hidden from active list
- [ ] Login page ticker scrolls (if active announcements)
- [ ] Non-admin: POST /api/v1/announcements → 403

### DB Reset
- [ ] Reset button visible only to admin
- [ ] Modal not dismissible by clicking outside
- [ ] "Reset Everything" disabled until both fields valid
- [ ] "RESET" must be exact (case-sensitive)
- [ ] Wrong password → inline error, fields re-enable
- [ ] Correct → success toast → redirect to login
- [ ] Admin can log in immediately after reset
- [ ] Second reset attempt within 60s → 429 message shown

---

## Environment Variables — New Additions

```env
# apps/dashboard/.env.local and .env.local.example
NEWS_API_KEY=    # newsapi.org key — leave empty to hide widget silently
```

No new backend env vars needed.
DB reset uses existing `DB_WRITER_INTERNAL_API_KEY`.

---

## Known Gotchas — Reminder

Before submitting any PR or finishing:
- [ ] `/api/v1/announcements` added to `AuthFilter.isProtected()`
- [ ] `/api/v1/admin` added to `AuthFilter.isProtected()`
- [ ] `/api/v1/public/announcements` in unauthenticated allowlist
- [ ] VN migration file uses next available version (check existing files)
- [ ] TENANT_ID is `t1` in all test env files
- [ ] db-writer port is 8090 in all new code (not 8081)
