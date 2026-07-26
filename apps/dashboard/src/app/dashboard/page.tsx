"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import AnalyticsPanel from "@/components/analytics/AnalyticsPanel";
import TeamPanel from "@/components/admin/TeamPanel";
import IntakeFieldsPanel from "@/components/admin/IntakeFieldsPanel";
import PriorityRulesPanel from "@/components/admin/PriorityRulesPanel";
import GeneralSettingsPanel from "@/components/admin/GeneralSettingsPanel";
import AnnouncementsPanel from "@/components/admin/AnnouncementsPanel";
import SystemPanel from "@/components/admin/SystemPanel";
import AnnouncementBanner from "@/components/announcements/AnnouncementBanner";
import Topbar from "@/components/layout/Topbar";
import Sidebar, { type NavKey } from "@/components/layout/Sidebar";
import { BASE as BADGE_BASE, identityBadgeStyle, priorityBadgeStyle, statusBadgeStyle } from "@/lib/badges";
import { tokens } from "@/lib/design-tokens";
import { Inbox, Mail, MessageCircle } from "lucide-react";

type Ticket = {
  id: string;
  ticket_number: string;
  status: string;
  category: string | null;
  priority_label: string | null;
  channel_origin: string;
  assigned_to: string | null;
  assigned_to_name: string | null;
  identity_status: string;
  created_at: string | null;
  citizen_name: string | null;
  citizen_email: string | null;
  citizen_phone: string | null;
};

function readCookie(name: string): string {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : "";
}

/**
 * Agent dashboard (Feature 12): Analytics / Ticket Queue / Administration.
 * UI_REVAMP_v2 §A3 shell: topbar (wordmark, announcement bell, role, logout) +
 * announcement banner + collapsible sidebar navigation (bottom tab bar on
 * mobile). The `tab` state model and tab contents are unchanged — the sidebar
 * simply drives the same union the old top tab bar did.
 */
export default function DashboardPage() {
  // Read synchronously (not in a useEffect) so an admin's first paint already
  // has the correct role — cookies are available client-side without waiting
  // for an effect, and deferring this caused the Administration nav item (and
  // AnalyticsPanel/TicketQueue's role-gated behaviour) to flash in a beat late.
  const [role] = useState(() => (typeof document !== "undefined" ? readCookie("role") : ""));
  const [tab, setTab] = useState<NavKey>("queue");

  return (
    // Background comes from dashboard/layout.tsx (gradient wash + optional image).
    <div className="min-h-screen">
      <Topbar role={role} />
      <AnnouncementBanner />
      <div className="flex">
        <Sidebar active={tab} role={role} onSelect={setTab} />
        <main className="min-w-0 flex-1 p-6 pb-24 md:pb-6">
          {tab === "queue" && <TicketQueue role={role} />}
          {tab === "analytics" && <AnalyticsPanel canViewAll={role === "admin" || role === "lead"} />}
          {tab === "admin" && role === "admin" && <Administration />}
        </main>
      </div>
    </div>
  );
}

type QueueScope = "confirmed" | "needs";
type SortDir = "asc" | "desc";

const QUEUE_STORAGE_KEY = "uniserve.ticketQueue";
const PAGE_SIZES = [30, 50, 100] as const;

const QUEUE_DEFAULTS = {
  scope: "confirmed" as QueueScope,
  page: 1,
  pageSize: 30,
  // Priority-first by default (docs/12_AGENT_DASHBOARD.md: "Priority score
  // descending... oldest high-priority first") — previously defaulted to
  // createdAt desc, which surfaced newest tickets regardless of urgency.
  // "priorityLabel" is already whitelisted server-side (TicketService.SORT_COLUMNS).
  sortBy: "priorityLabel",
  sortDir: "desc" as SortDir,
};

/** Column header → server `sortBy` key. A null key means the column is not sortable. */
const QUEUE_COLUMNS: { label: string; sortKey: string | null }[] = [
  { label: "Ticket", sortKey: "ticketNumber" },
  { label: "Status", sortKey: "status" },
  { label: "Priority", sortKey: "priorityLabel" },
  { label: "Category", sortKey: "category" },
  { label: "Channel", sortKey: "channel" },
  { label: "Identity", sortKey: "identityStatus" },
  { label: "Name", sortKey: "citizenName" },
  { label: "Email", sortKey: "citizenEmail" },
  { label: "Mobile", sortKey: "citizenPhone" },
  { label: "Created", sortKey: "createdAt" },
  { label: "Assigned to", sortKey: null },
];

function TicketQueue({ role }: { role: string }) {
  const showToggle = role === "admin" || role === "lead";

  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  const [scope, setScope] = useState<QueueScope>(QUEUE_DEFAULTS.scope);
  const [page, setPage] = useState(QUEUE_DEFAULTS.page);
  const [pageSize, setPageSize] = useState<number>(QUEUE_DEFAULTS.pageSize);
  const [sortBy, setSortBy] = useState(QUEUE_DEFAULTS.sortBy);
  const [sortDir, setSortDir] = useState<SortDir>(QUEUE_DEFAULTS.sortDir);

  // Requirement 7: restore persisted view state on mount (returning from a
  // ticket-detail page re-mounts this component, so this doubles as "refresh on
  // return" and lands the user on the same scope/page/sort they left).
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(QUEUE_STORAGE_KEY);
      if (raw) {
        const s = JSON.parse(raw) as Partial<typeof QUEUE_DEFAULTS>;
        if (s.scope === "confirmed" || s.scope === "needs") setScope(s.scope);
        if (typeof s.page === "number" && s.page >= 1) setPage(s.page);
        if (s.pageSize === 30 || s.pageSize === 50 || s.pageSize === 100) setPageSize(s.pageSize);
        if (typeof s.sortBy === "string" && s.sortBy) setSortBy(s.sortBy);
        if (s.sortDir === "asc" || s.sortDir === "desc") setSortDir(s.sortDir);
      }
    } catch {
      // ignore malformed storage
    }
    setHydrated(true);
  }, []);

  // Requirement 7: persist view state whenever any of it changes.
  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(
        QUEUE_STORAGE_KEY,
        JSON.stringify({ scope, page, pageSize, sortBy, sortDir }),
      );
    } catch {
      // ignore storage failures (e.g. private mode quota)
    }
  }, [hydrated, scope, page, pageSize, sortBy, sortDir]);

  // Server-side fetch of the CURRENT view (all params). `background` keeps the
  // table visible during auto/manual refresh instead of flipping to a spinner.
  const load = useCallback(
    (background: boolean) => {
      const params = new URLSearchParams();
      if (role === "agent") {
        params.set("assignedTo", "me");
      } else if (showToggle) {
        params.set(
          "identityStatus",
          scope === "confirmed" ? "confirmed" : "pending,anonymous",
        );
      }
      params.set("page", String(page));
      params.set("pageSize", String(pageSize));
      params.set("sortBy", sortBy);
      params.set("sortDir", sortDir);

      if (background) setRefreshing(true);
      else setLoading(true);

      fetch(`/api/tickets?${params.toString()}`)
        .then((r) => r.json())
        .then((d) => {
          setTickets(d.tickets ?? []);
          setTotal(typeof d.total === "number" ? d.total : 0);
        })
        .catch(() => {
          // leave the previous view in place on a transient error
        })
        .finally(() => {
          if (background) setRefreshing(false);
          else setLoading(false);
        });
    },
    [role, showToggle, scope, page, pageSize, sortBy, sortDir],
  );

  // Foreground fetch whenever the view changes (and once after hydration).
  useEffect(() => {
    if (!hydrated) return;
    load(false);
  }, [hydrated, load]);

  // Requirement 5: auto-refresh the current view every 30s; cleared on unmount.
  useEffect(() => {
    if (!hydrated) return;
    const id = setInterval(() => load(true), 30000);
    return () => clearInterval(id);
  }, [hydrated, load]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function changeScope(next: QueueScope) {
    if (next === scope) return;
    setScope(next);
    setPage(1); // scope change resets to page 1
  }

  function changePageSize(next: number) {
    if (next === pageSize) return;
    setPageSize(next);
    setPage(1); // pageSize change resets to page 1
  }

  function toggleSort(key: string) {
    if (key === sortBy) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortDir("desc");
    }
    setPage(1); // sort change resets to page 1
  }

  const scopes: { key: QueueScope; label: string }[] = [
    { key: "confirmed", label: "Confirmed" },
    { key: "needs", label: "Needs identity" },
  ];

  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  useEffect(() => {
    if (!loading && !refreshing) setLastUpdated(new Date());
  }, [loading, refreshing, tickets]);

  const CHANNEL_ICON: Record<string, typeof Mail> = { email: Mail, whatsapp: MessageCircle };

  return (
    <div className="space-y-4">
      {showToggle && (
        <div className="flex gap-2 rounded-lg bg-white p-1 shadow-sm">
          {scopes.map((s) => (
            <button
              key={s.key}
              onClick={() => changeScope(s.key)}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                scope === s.key
                  ? "bg-brand-teal font-semibold text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Requirement 4/6: pagination + page size + manual refresh, above the table. */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-2 shadow-sm">
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span>
            {total} {total === 1 ? "ticket" : "tickets"}
          </span>
          <label className="flex items-center gap-1">
            <span className="text-slate-600">Per page</span>
            <select
              value={pageSize}
              onChange={(e) => changePageSize(Number(e.target.value))}
              className="rounded border bg-white px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          {lastUpdated && (
            <span className="text-xs text-slate-500">
              Last updated {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50 active:scale-[0.97]"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50 active:scale-[0.97]"
          >
            Prev
          </button>
          <span className="text-slate-600">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50 active:scale-[0.97]"
          >
            Next
          </button>
        </div>
      </div>

      {loading ? (
        <div className="overflow-x-auto rounded-lg border bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                {QUEUE_COLUMNS.map((col) => (
                  <th key={col.label} scope="col" className="whitespace-nowrap p-2 font-medium">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t">
                  {QUEUE_COLUMNS.map((col) => (
                    <td key={col.label} className="p-2">
                      <div className="h-4 w-full animate-pulse rounded bg-slate-100" />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : tickets.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border bg-white p-4 text-sm text-slate-600 shadow-sm">
          <Inbox className="h-4 w-4 text-slate-400" aria-hidden />
          No tickets match &ldquo;{scope === "confirmed" ? "Confirmed" : "Needs identity"}&rdquo; for this view.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                {QUEUE_COLUMNS.map((col) => (
                  <th
                    key={col.label}
                    scope="col"
                    className="whitespace-nowrap p-2"
                    aria-sort={
                      col.sortKey
                        ? sortBy === col.sortKey
                          ? sortDir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                        : undefined
                    }
                  >
                    {col.sortKey ? (
                      <button
                        onClick={() => toggleSort(col.sortKey as string)}
                        className="inline-flex items-center gap-1 font-medium hover:text-slate-900"
                      >
                        {col.label}
                        {sortBy === col.sortKey && (
                          <span aria-hidden>{sortDir === "asc" ? "▲" : "▼"}</span>
                        )}
                      </button>
                    ) : (
                      col.label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tickets.map((t, i) => {
                const ChannelIcon = CHANNEL_ICON[t.channel_origin];
                const channelToken = (tokens.channel as Record<string, { color: string }>)[t.channel_origin];
                return (
                  <tr
                    key={t.id}
                    className={`border-t transition-[background-color,transform,box-shadow] duration-150 hover:-translate-y-px hover:bg-brand-tealTint/50 hover:shadow-sm ${
                      t.priority_label === "critical" ? "bg-red-50/60" : i % 2 === 1 ? "bg-slate-50/60" : "bg-white"
                    }`}
                  >
                    <td className="whitespace-nowrap p-2 font-medium">
                      <span
                        className="mr-1.5 inline-block h-2 w-2 shrink-0 rounded-full align-middle"
                        style={{ backgroundColor: (tokens.priority as Record<string, { dot: string }>)[t.priority_label ?? ""]?.dot ?? "#94a3b8" }}
                        aria-hidden
                      />
                      <Link href={`/dashboard/tickets/${t.id}`} className="text-brand-teal hover:underline">
                        {t.ticket_number}
                      </Link>
                    </td>
                    <td className="p-2">
                      <span className={BADGE_BASE} style={statusBadgeStyle(t.status)}>
                        {t.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="p-2">
                      {t.priority_label ? (
                        <span className={BADGE_BASE} style={priorityBadgeStyle(t.priority_label)}>
                          {t.priority_label}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="p-2">{t.category ?? "—"}</td>
                    <td className="p-2">
                      <span className="inline-flex items-center gap-1.5 capitalize">
                        {ChannelIcon && (
                          <ChannelIcon className="h-3.5 w-3.5" style={{ color: channelToken?.color }} aria-hidden />
                        )}
                        {t.channel_origin}
                      </span>
                    </td>
                    <td className="p-2">
                      {t.identity_status ? (
                        <span className={BADGE_BASE} style={identityBadgeStyle(t.identity_status)}>
                          {t.identity_status}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="whitespace-nowrap p-2">{t.citizen_name ?? "—"}</td>
                    <td className="whitespace-nowrap p-2">{t.citizen_email ?? "—"}</td>
                    <td className="whitespace-nowrap p-2">{t.citizen_phone ?? "—"}</td>
                    <td className="whitespace-nowrap p-2">{t.created_at ?? "—"}</td>
                    <td className="p-2">
                      {t.assigned_to_name ?? <span className="text-slate-500">Unassigned</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type AdminSubTab = "team" | "intake" | "priority" | "settings" | "announcements" | "system";
const ADMIN_SUBTAB_KEY = "uniserve.adminSubTab";

function Administration() {
  // Persisted in sessionStorage (not lifted to a parent) so it survives this
  // component unmounting when the admin switches to Analytics/Queue and back.
  const [subTab, setSubTab] = useState<AdminSubTab>(() => {
    if (typeof sessionStorage === "undefined") return "team";
    const saved = sessionStorage.getItem(ADMIN_SUBTAB_KEY);
    const valid: AdminSubTab[] = ["team", "intake", "priority", "settings", "announcements", "system"];
    return (valid as string[]).includes(saved ?? "") ? (saved as AdminSubTab) : "team";
  });

  function selectSubTab(key: AdminSubTab) {
    setSubTab(key);
    try {
      sessionStorage.setItem(ADMIN_SUBTAB_KEY, key);
    } catch {
      // ignore storage failures (e.g. private mode quota)
    }
  }

  const subTabs: { key: AdminSubTab; label: string }[] = [
    { key: "team", label: "Team" },
    { key: "intake", label: "Intake Fields" },
    { key: "priority", label: "Priority Rules" },
    { key: "settings", label: "Settings" },
    { key: "announcements", label: "Announcements" },
    { key: "system", label: "System" },
  ];

  return (
    <div>
      <nav className="mb-4 flex gap-2 border-b">
        {subTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => selectSubTab(t.key)}
            className={`px-3 py-2 text-sm transition-colors ${
              subTab === t.key ? "border-b-2 border-brand-teal font-semibold text-brand-teal" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {subTab === "team" && <TeamPanel />}
      {subTab === "intake" && <IntakeFieldsPanel />}
      {subTab === "priority" && <PriorityRulesPanel />}
      {subTab === "settings" && <GeneralSettingsPanel />}
      {subTab === "announcements" && <AnnouncementsPanel />}
      {subTab === "system" && <SystemPanel />}
    </div>
  );
}
