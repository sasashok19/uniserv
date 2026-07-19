"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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

function TicketQueue({ role }: { role: string }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState<QueueScope>("confirmed");

  const showToggle = role === "admin" || role === "lead";

  useEffect(() => {
    let query = "";
    if (role === "agent") {
      query = "?assignedTo=me";
    } else if (showToggle) {
      query =
        scope === "confirmed"
          ? "?identityStatus=confirmed"
          : "?identityStatus=pending,anonymous";
    }
    setLoading(true);
    fetch(`/api/tickets${query}`)
      .then((r) => r.json())
      .then((d) => setTickets(d.tickets ?? []))
      .finally(() => setLoading(false));
  }, [role, scope, showToggle]);

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
              onClick={() => setScope(s.key)}
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

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : tickets.length === 0 ? (
        <p className="text-sm">No tickets.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-muted-foreground">
              <tr>
                <th className="p-2">Ticket</th>
                <th className="p-2">Status</th>
                <th className="p-2">Priority</th>
                <th className="p-2">Category</th>
                <th className="p-2">Channel</th>
                <th className="p-2">Identity</th>
                <th className="p-2">Assigned to</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.id} className="border-t hover:bg-indigo-50/40">
                  <td className="p-2 font-medium">
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
