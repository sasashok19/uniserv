"use client";

import { useEffect, useState } from "react";

type Ticket = {
  id: string;
  ticket_number: string;
  status: string;
  category: string | null;
  priority_label: string | null;
  channel_origin: string;
  assigned_to: string | null;
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
    <main className="mx-auto max-w-4xl p-6">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-xl font-bold">UniServe</h1>
        <span className="rounded-full border px-3 py-1 text-xs uppercase">{role || "guest"}</span>
      </div>
      <nav className="mb-6 flex gap-2 border-b">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 text-sm ${tab === t.key ? "border-b-2 border-black font-semibold" : "text-muted-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "queue" && <TicketQueue role={role} />}
      {tab === "analytics" && <Analytics />}
      {tab === "admin" && role === "admin" && <Administration />}
    </main>
  );
}

function TicketQueue({ role }: { role: string }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const query = role === "agent" ? "?assignedTo=me" : "";
    fetch(`/api/tickets${query}`)
      .then((r) => r.json())
      .then((d) => setTickets(d.tickets ?? []))
      .finally(() => setLoading(false));
  }, [role]);

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (tickets.length === 0) return <p className="text-sm">No tickets.</p>;

  return (
    <table className="w-full text-left text-sm">
      <thead className="text-muted-foreground">
        <tr>
          <th className="p-2">Ticket</th>
          <th className="p-2">Status</th>
          <th className="p-2">Priority</th>
          <th className="p-2">Category</th>
          <th className="p-2">Channel</th>
        </tr>
      </thead>
      <tbody>
        {tickets.map((t) => (
          <tr key={t.id} className="border-t">
            <td className="p-2 font-medium">{t.ticket_number}</td>
            <td className="p-2">{t.status}</td>
            <td className="p-2">{t.priority_label ?? "—"}</td>
            <td className="p-2">{t.category ?? "—"}</td>
            <td className="p-2">{t.channel_origin}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Analytics() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {["Ticket volume", "SLA performance", "Priority distribution", "Agent performance"].map(
        (title) => (
          <div key={title} className="rounded-lg border p-4">
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="mt-2 text-xs text-muted-foreground">
              Chart renders from analytics API (Phase 1: data available via db-writer).
            </p>
          </div>
        ),
      )}
    </div>
  );
}

function Administration() {
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ name: "", email: "", role: "agent", password: "" });

  async function addAgent(e: React.FormEvent) {
    e.preventDefault();
    const resp = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setMsg(resp.ok ? "Agent created." : "Failed to create agent.");
  }

  return (
    <form onSubmit={addAgent} className="max-w-sm space-y-3">
      <h3 className="text-sm font-semibold">Add agent</h3>
      {(["name", "email", "password"] as const).map((f) => (
        <input
          key={f}
          className="w-full rounded border p-2 text-sm"
          placeholder={f}
          value={form[f]}
          onChange={(e) => setForm({ ...form, [f]: e.target.value })}
        />
      ))}
      <select
        className="w-full rounded border p-2 text-sm"
        value={form.role}
        onChange={(e) => setForm({ ...form, role: e.target.value })}
      >
        <option value="agent">agent</option>
        <option value="lead">lead</option>
        <option value="admin">admin</option>
      </select>
      <button className="rounded bg-black px-3 py-2 text-sm text-white">Create</button>
      {msg && <p className="text-sm">{msg}</p>}
    </form>
  );
}
