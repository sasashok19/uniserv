"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const PERIODS = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "365d", label: "Last 12 months" },
];

const PRIORITIES = ["critical", "high", "medium", "low"] as const;
const PRIORITY_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#f97316",
  medium: "#eab308",
  low: "#16a34a",
  unlabelled: "#94a3b8",
};
const CHANNEL_COLORS: Record<string, string> = {
  email: "#4f46e5",
  whatsapp: "#22c55e",
  unknown: "#94a3b8",
};

type Agent = { id: string; name: string };
type Customer = { id: string; name: string | null; email: string | null; phone: string | null };

type Filters = {
  period: string;
  agentId: string;
  identityId: string;
  category: string;
  priorityLabel: string;
};

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">{title}</h3>
      {children}
    </div>
  );
}

function EmptyState() {
  return <p className="py-8 text-center text-sm text-muted-foreground">No data for this filter combination.</p>;
}

export default function AnalyticsPanel({ canViewAll }: { canViewAll: boolean }) {
  const [filters, setFilters] = useState<Filters>({
    period: "30d",
    agentId: "",
    identityId: "",
    category: "",
    priorityLabel: "",
  });
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerLabel, setCustomerLabel] = useState("");
  const [customerOptions, setCustomerOptions] = useState<Customer[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);

  const [volume, setVolume] = useState<any[]>([]);
  const [sla, setSla] = useState<{ met: number; breached: number; slaMetPercent: number } | null>(null);
  const [priority, setPriority] = useState<Record<string, number>>({});
  const [agentPerf, setAgentPerf] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!canViewAll) return;
    fetch("/api/analytics/agents-directory")
      .then((r) => r.json())
      .then((d) => setAgents(d.agents ?? []));
  }, [canViewAll]);

  useEffect(() => {
    if (!canViewAll || customerQuery.trim().length < 2) {
      setCustomerOptions([]);
      return;
    }
    const handle = setTimeout(() => {
      fetch(`/api/analytics/customers?q=${encodeURIComponent(customerQuery)}`)
        .then((r) => r.json())
        .then((d) => setCustomerOptions(d.customers ?? []));
    }, 250);
    return () => clearTimeout(handle);
  }, [customerQuery, canViewAll]);

  const query = useMemo(() => {
    const q = new URLSearchParams();
    q.set("period", filters.period);
    if (filters.agentId) q.set("agentId", filters.agentId);
    if (filters.identityId) q.set("identityId", filters.identityId);
    if (filters.category) q.set("category", filters.category);
    if (filters.priorityLabel) q.set("priorityLabel", filters.priorityLabel);
    return q.toString();
  }, [filters]);

  useEffect(() => {
    setLoading(true);
    const calls: Promise<void>[] = [
      fetch(`/api/analytics/volume?${query}`).then((r) => r.json()).then((d) => setVolume(d.data ?? [])),
      fetch(`/api/analytics/sla?${query}`).then((r) => r.json()).then((d) => setSla(d)),
      fetch(`/api/analytics/priority?${query}`).then((r) => r.json()).then((d) => setPriority(d.data ?? {})),
    ];
    if (canViewAll) {
      calls.push(
        fetch(`/api/analytics/agents?${query}`).then((r) => r.json()).then((d) => setAgentPerf(d.data ?? [])),
      );
    }
    Promise.all(calls).finally(() => setLoading(false));
  }, [query, canViewAll]);

  const channels = useMemo(() => {
    const set = new Set<string>();
    volume.forEach((v) => Object.keys(v.byChannel ?? {}).forEach((c) => set.add(c)));
    return Array.from(set);
  }, [volume]);

  const priorityData = PRIORITIES.concat(["unlabelled"] as any)
    .map((label) => ({ label, count: priority[label] ?? 0 }))
    .filter((d) => d.count > 0 || !filters.priorityLabel);

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-white p-3 shadow-sm">
        <div>
          <label className="block text-xs text-muted-foreground">Time frame</label>
          <select
            className="rounded border p-2 text-sm"
            value={filters.period}
            onChange={(e) => setFilters({ ...filters, period: e.target.value })}
          >
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {canViewAll && (
          <div>
            <label className="block text-xs text-muted-foreground">Agent</label>
            <select
              className="rounded border p-2 text-sm"
              value={filters.agentId}
              onChange={(e) => setFilters({ ...filters, agentId: e.target.value })}
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {canViewAll && (
          <div className="relative">
            <label className="block text-xs text-muted-foreground">Customer</label>
            <input
              className="w-48 rounded border p-2 text-sm"
              placeholder="Search name/email/phone"
              value={customerLabel || customerQuery}
              onChange={(e) => {
                setCustomerQuery(e.target.value);
                setCustomerLabel("");
                setFilters({ ...filters, identityId: "" });
              }}
            />
            {customerOptions.length > 0 && !filters.identityId && (
              <ul className="absolute z-10 mt-1 w-64 rounded border bg-white shadow-lg">
                {customerOptions.map((c) => (
                  <li
                    key={c.id}
                    className="cursor-pointer px-2 py-1 text-sm hover:bg-indigo-50"
                    onClick={() => {
                      setFilters({ ...filters, identityId: c.id });
                      setCustomerLabel(c.name || c.email || c.phone || c.id);
                      setCustomerOptions([]);
                    }}
                  >
                    {c.name || "—"} · {c.email || c.phone || "no contact on file"}
                  </li>
                ))}
              </ul>
            )}
            {filters.identityId && (
              <button
                className="ml-1 text-xs text-indigo-600 hover:underline"
                onClick={() => {
                  setFilters({ ...filters, identityId: "" });
                  setCustomerLabel("");
                  setCustomerQuery("");
                }}
              >
                clear
              </button>
            )}
          </div>
        )}

        <div>
          <label className="block text-xs text-muted-foreground">Priority</label>
          <select
            className="rounded border p-2 text-sm"
            value={filters.priorityLabel}
            onChange={(e) => setFilters({ ...filters, priorityLabel: e.target.value })}
          >
            <option value="">All priorities</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-muted-foreground">Category</label>
          <input
            className="w-36 rounded border p-2 text-sm"
            placeholder="e.g. billing"
            value={filters.category}
            onChange={(e) => setFilters({ ...filters, category: e.target.value })}
          />
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <ChartCard title="Ticket volume">
            {volume.length === 0 ? (
              <EmptyState />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={volume}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Legend />
                  {channels.map((c) => (
                    <Bar
                      key={c}
                      dataKey={(d: any) => d.byChannel?.[c] ?? 0}
                      name={c}
                      stackId="volume"
                      fill={CHANNEL_COLORS[c] ?? "#94a3b8"}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          <ChartCard title="SLA performance">
            {!sla || sla.met + sla.breached === 0 ? (
              <EmptyState />
            ) : (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width="60%" height={180}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: "Met", value: sla.met },
                        { name: "Breached", value: sla.breached },
                      ]}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={45}
                      outerRadius={70}
                    >
                      <Cell fill="#16a34a" />
                      <Cell fill="#dc2626" />
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div>
                  <p className="text-2xl font-bold text-green-600">{sla.slaMetPercent}%</p>
                  <p className="text-xs text-muted-foreground">SLA met</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {sla.met} met · {sla.breached} breached
                  </p>
                </div>
              </div>
            )}
          </ChartCard>

          <ChartCard title="Priority distribution">
            {priorityData.every((d) => d.count === 0) ? (
              <EmptyState />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={priorityData} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 11 }} width={70} />
                  <Tooltip />
                  <Bar dataKey="count" radius={4}>
                    {priorityData.map((d) => (
                      <Cell key={d.label} fill={PRIORITY_COLORS[d.label] ?? "#94a3b8"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          <ChartCard title="Agent performance">
            {!canViewAll ? (
              <p className="py-8 text-center text-sm text-muted-foreground">Visible to leads and admins only.</p>
            ) : agentPerf.length === 0 ? (
              <EmptyState />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={agentPerf}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="agentName" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="resolved" name="Resolved" fill="#4f46e5" radius={4} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>
      )}
    </div>
  );
}
