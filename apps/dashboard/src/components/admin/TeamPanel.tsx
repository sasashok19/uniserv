"use client";

import { useEffect, useState } from "react";

import { activeBadgeClass, roleBadgeClass } from "@/lib/badges";

type Agent = {
  id: string;
  name: string;
  email: string;
  role: "admin" | "lead" | "agent";
  is_active: number;
  created_at: string;
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ROLES = ["admin", "lead", "agent"] as const;

function fieldError(field: string, value: string, opts?: { requirePassword?: boolean }): string {
  if (field === "name" && !value.trim()) return "Name is required";
  if (field === "email" && !EMAIL_RE.test(value)) return "Enter a valid email address";
  if (field === "password" && opts?.requirePassword && value.length < 8) {
    return "Password must be at least 8 characters";
  }
  return "";
}

/** Administration → Team (Feature 12/15): list, add, edit, and reset-password for agents/leads/admins. */
export default function TeamPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    setLoading(true);
    const resp = await fetch("/api/agents");
    const data = await resp.json().catch(() => ({}));
    setAgents(data.agents ?? []);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Team</h3>
        <button
          onClick={() => {
            setShowAdd((v) => !v);
            setEditingId(null);
          }}
          className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          {showAdd ? "Cancel" : "Add new"}
        </button>
      </div>

      {message && <p className="rounded-lg bg-indigo-50 p-2 text-sm text-indigo-700">{message}</p>}

      {showAdd && (
        <AddAgentForm
          onDone={(msg) => {
            setShowAdd(false);
            setMessage(msg);
            refresh();
          }}
        />
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : agents.length === 0 ? (
        <p className="text-sm text-muted-foreground">No team members yet.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th className="p-2">Name</th>
              <th className="p-2">Email</th>
              <th className="p-2">Role</th>
              <th className="p-2">Status</th>
              <th className="p-2">Joined</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id} className="border-t hover:bg-muted/30">
                <td className="p-2 font-medium">{a.name}</td>
                <td className="p-2 text-muted-foreground">{a.email}</td>
                <td className="p-2">
                  <span className={roleBadgeClass(a.role)}>{a.role}</span>
                </td>
                <td className="p-2">
                  <span className={activeBadgeClass(!!a.is_active)}>
                    {a.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="p-2 text-muted-foreground">{a.created_at?.slice(0, 10)}</td>
                <td className="p-2 text-right">
                  <button
                    onClick={() => {
                      setEditingId(editingId === a.id ? null : a.id);
                      setShowAdd(false);
                    }}
                    className="rounded border px-3 py-1 text-xs hover:bg-muted/50"
                  >
                    {editingId === a.id ? "Close" : "Edit"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editingId && (
        <EditAgentForm
          agent={agents.find((a) => a.id === editingId)!}
          onDone={(msg) => {
            setEditingId(null);
            setMessage(msg);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function AddAgentForm({ onDone }: { onDone: (msg: string) => void }) {
  const [form, setForm] = useState({ name: "", email: "", role: "agent", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState("");

  function validate(): boolean {
    const next = {
      name: fieldError("name", form.name),
      email: fieldError("email", form.email),
      password: fieldError("password", form.password, { requirePassword: true }),
    };
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    if (!validate()) return;
    setSubmitting(true);
    const resp = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setSubmitting(false);
    if (resp.ok) {
      onDone(`${form.name} added to the team.`);
      return;
    }
    const data = await resp.json().catch(() => ({}));
    setServerError(data?.error?.message ?? "Failed to add team member.");
  }

  return (
    <form onSubmit={submit} className="max-w-sm space-y-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-4">
      <div>
        <input
          className="w-full rounded border p-2 text-sm"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
      </div>
      <div>
        <input
          className="w-full rounded border p-2 text-sm"
          placeholder="Email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
        />
        {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email}</p>}
      </div>
      <div>
        <input
          type="password"
          className="w-full rounded border p-2 text-sm"
          placeholder="Password (min 8 characters)"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
        />
        {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password}</p>}
      </div>
      <select
        className="w-full rounded border p-2 text-sm"
        value={form.role}
        onChange={(e) => setForm({ ...form, role: e.target.value })}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      {serverError && <p className="text-xs text-red-600">{serverError}</p>}
      <button
        disabled={submitting}
        className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
      >
        {submitting ? "Adding…" : "Add team member"}
      </button>
    </form>
  );
}

function EditAgentForm({ agent, onDone }: { agent: Agent; onDone: (msg: string) => void }) {
  const [name, setName] = useState(agent.name);
  const [role, setRole] = useState(agent.role);
  const [isActive, setIsActive] = useState(!!agent.is_active);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState("");

  function validate(): boolean {
    const next: Record<string, string> = { name: fieldError("name", name) };
    if (password || confirm) {
      const pwErr = fieldError("password", password, { requirePassword: true });
      if (pwErr) next.password = pwErr;
      else if (password !== confirm) next.password = "Passwords do not match";
    }
    setErrors(next);
    return !Object.values(next).some(Boolean);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    if (!validate()) return;
    setSubmitting(true);
    const resp = await fetch(`/api/agents/${agent.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, role, isActive }),
    });
    if (!resp.ok) {
      setSubmitting(false);
      const data = await resp.json().catch(() => ({}));
      setServerError(data?.error?.message ?? "Failed to save changes.");
      return;
    }
    if (password) {
      const pwResp = await fetch(`/api/agents/${agent.id}/password`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      setSubmitting(false);
      if (!pwResp.ok) {
        const data = await pwResp.json().catch(() => ({}));
        setServerError(data?.error?.message ?? "Details saved, but password reset failed.");
        return;
      }
      onDone(`${name}'s details and password were updated.`);
      return;
    }
    setSubmitting(false);
    onDone(`${name}'s details were updated.`);
  }

  return (
    <form onSubmit={submit} className="max-w-sm space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h4 className="text-sm font-semibold text-slate-700">Edit {agent.name}</h4>
      <div>
        <label className="text-xs text-muted-foreground">Name</label>
        <input
          className="w-full rounded border p-2 text-sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
      </div>
      <div>
        <label className="text-xs text-muted-foreground">Email (cannot be changed)</label>
        <input className="w-full rounded border bg-slate-100 p-2 text-sm text-muted-foreground" value={agent.email} disabled />
      </div>
      <div>
        <label className="text-xs text-muted-foreground">Role</label>
        <select className="w-full rounded border p-2 text-sm" value={role} onChange={(e) => setRole(e.target.value as Agent["role"])}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
        Active
      </label>

      <div className="border-t pt-3">
        <p className="mb-2 text-xs font-medium text-slate-600">Reset password (optional)</p>
        <input
          type="password"
          className="mb-2 w-full rounded border p-2 text-sm"
          placeholder="New password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <input
          type="password"
          className="w-full rounded border p-2 text-sm"
          placeholder="Confirm new password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password}</p>}
      </div>

      {serverError && <p className="text-xs text-red-600">{serverError}</p>}
      <button
        disabled={submitting}
        className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
      >
        {submitting ? "Saving…" : "Save changes"}
      </button>
    </form>
  );
}
