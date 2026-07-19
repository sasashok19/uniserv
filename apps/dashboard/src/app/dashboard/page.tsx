"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import AnalyticsPanel from "@/components/analytics/AnalyticsPanel";
import TeamPanel from "@/components/admin/TeamPanel";
import IntakeFieldsPanel from "@/components/admin/IntakeFieldsPanel";
import PriorityRulesPanel from "@/components/admin/PriorityRulesPanel";
import GeneralSettingsPanel from "@/components/admin/GeneralSettingsPanel";
import { identityBadgeClass, priorityBadgeClass, statusBadgeClass } from "@/lib/badges";

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

/** Agent dashboard (Feature 12): Analytics / Ticket Queue / Administration tabs. */
export default function DashboardPage() {
  const [role, setRole] = useState("");
  const [tab, setTab] = useState<"analytics" | "queue" | "admin">("queue");

  useEffect(() => {
    setRole(readCookie("role"));
  }, []);

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "analytics", label: "Analytics" },
    { key: "queue", label: "Ticket Queue" },
    ...(role === "admin"
      ? [{ key: "admin" as const, label: "Administration" }]
      : []),
  ];

  return (
    <main className="mx-auto max-w-4xl bg-slate-50 p-6">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-xl font-bold text-indigo-700">UniServe</h1>
        <span className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs uppercase text-indigo-700">
          {role || "guest"}
        </span>
      </div>
      <nav className="mb-6 flex gap-2 rounded-lg bg-white p-1 shadow-sm">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-md px-3 py-2 text-sm transition-colors ${
              tab === t.key
                ? "bg-indigo-600 font-semibold text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "queue" && <TicketQueue role={role} />}
      {tab === "analytics" && <AnalyticsPanel canViewAll={role === "admin" || role === "lead"} />}
      {tab === "admin" && role === "admin" && <Administration />}
    </main>
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
  sortBy: "createdAt",
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
                  ? "bg-indigo-600 font-semibold text-white"
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
            <span className="text-muted-foreground">Per page</span>
            <select
              value={pageSize}
              onChange={(e) => changePageSize(Number(e.target.value))}
              className="rounded border bg-white px-2 py-1 text-sm focus:border-indigo-400 focus:outline-none"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            Prev
          </button>
          <span className="text-slate-600">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border px-3 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : tickets.length === 0 ? (
        <p className="text-sm">No tickets.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-muted-foreground">
              <tr>
                {QUEUE_COLUMNS.map((col) => (
                  <th key={col.label} className="whitespace-nowrap p-2">
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
              {tickets.map((t) => (
                <tr key={t.id} className="border-t hover:bg-indigo-50/40">
                  <td className="whitespace-nowrap p-2 font-medium">
                    <Link href={`/dashboard/tickets/${t.id}`} className="text-indigo-700 hover:underline">
                      {t.ticket_number}
                    </Link>
                  </td>
                  <td className="p-2">
                    <span className={statusBadgeClass(t.status)}>{t.status.replace("_", " ")}</span>
                  </td>
                  <td className="p-2">
                    {t.priority_label ? (
                      <span className={priorityBadgeClass(t.priority_label)}>{t.priority_label}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="p-2">{t.category ?? "—"}</td>
                  <td className="p-2 capitalize">{t.channel_origin}</td>
                  <td className="p-2">
                    {t.identity_status ? (
                      <span className={identityBadgeClass(t.identity_status)}>{t.identity_status}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="whitespace-nowrap p-2">{t.citizen_name ?? "—"}</td>
                  <td className="whitespace-nowrap p-2">{t.citizen_email ?? "—"}</td>
                  <td className="whitespace-nowrap p-2">{t.citizen_phone ?? "—"}</td>
                  <td className="whitespace-nowrap p-2">{t.created_at ?? "—"}</td>
                  <td className="p-2">
                    {t.assigned_to_name ?? (
                      <span className="text-muted-foreground">Unassigned</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Administration() {
  const [subTab, setSubTab] = useState<"team" | "intake" | "priority" | "settings">("team");
  const subTabs: { key: typeof subTab; label: string }[] = [
    { key: "team", label: "Team" },
    { key: "intake", label: "Intake Fields" },
    { key: "priority", label: "Priority Rules" },
    { key: "settings", label: "Settings" },
  ];

  return (
    <div>
      <nav className="mb-4 flex gap-2 border-b">
        {subTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setSubTab(t.key)}
            className={`px-3 py-2 text-sm ${
              subTab === t.key ? "border-b-2 border-indigo-600 font-semibold text-indigo-700" : "text-muted-foreground"
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
    </div>
  );
}
