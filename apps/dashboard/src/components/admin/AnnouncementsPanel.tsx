"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { Announcement } from "@/components/announcements/AnnouncementBell";

/**
 * Administration → Announcements (UI_REVAMP_v2 Feature C): list active +
 * expired/inactive notices with create/edit/deactivate/delete. Plain-Tailwind
 * modal (no shadcn), mirroring the other admin panels' styling.
 */
export default function AnnouncementsPanel() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Announcement | "new" | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/announcements");
      const data = await resp.json().catch(() => ({}));
      setItems(Array.isArray(data.announcements) ? data.announcements : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  const isLive = (a: Announcement) => a.is_active === 1 && (!a.expires_at || a.expires_at > now);
  const active = items.filter(isLive);
  const inactive = items.filter((a) => !isLive(a));

  async function toggleActive(a: Announcement) {
    await fetch(`/api/announcements/${a.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isActive: a.is_active !== 1 }),
    });
    setMessage(a.is_active === 1 ? "Announcement deactivated." : "Announcement reactivated.");
    refresh();
  }

  async function remove(a: Announcement) {
    if (!window.confirm(`Delete announcement "${a.title}"? This cannot be undone.`)) return;
    await fetch(`/api/announcements/${a.id}`, { method: "DELETE" });
    setMessage("Announcement deleted.");
    refresh();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Announcements</h3>
        <button
          onClick={() => setEditing("new")}
          className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          New announcement
        </button>
      </div>

      {message && <p className="rounded-lg bg-indigo-50 p-2 text-sm text-indigo-700">{message}</p>}

      {loading ? (
        <div className="space-y-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      ) : (
        <>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Active ({active.length})</p>
          {active.length === 0 && <p className="text-sm text-muted-foreground">No active announcements.</p>}
          {active.map((a) => (
            <AnnouncementCard key={a.id} a={a} live onEdit={() => setEditing(a)} onToggle={() => toggleActive(a)} onDelete={() => remove(a)} />
          ))}

          <button
            onClick={() => setShowInactive((v) => !v)}
            className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-600"
          >
            {showInactive ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            Expired / Inactive ({inactive.length})
          </button>
          {showInactive &&
            inactive.map((a) => (
              <AnnouncementCard key={a.id} a={a} live={false} onEdit={() => setEditing(a)} onToggle={() => toggleActive(a)} onDelete={() => remove(a)} />
            ))}
        </>
      )}

      {editing && (
        <EditModal
          announcement={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(msg) => {
            setEditing(null);
            setMessage(msg);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function AnnouncementCard({
  a,
  live,
  onEdit,
  onToggle,
  onDelete,
}: {
  a: Announcement;
  live: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={`rounded-lg border p-3 ${live ? "border-emerald-200 bg-white" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${live ? "bg-emerald-500" : "bg-slate-300"}`} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-800">{a.title}</p>
          <p className="mt-0.5 text-sm text-muted-foreground">{a.body}</p>
          <p className="mt-1 text-xs text-slate-400">
            {a.expires_at ? `Expires: ${a.expires_at}` : "Never expires"} · created {a.created_at}
          </p>
        </div>
      </div>
      <div className="mt-2 flex gap-2">
        <button onClick={onEdit} className="rounded border px-3 py-1 text-xs hover:bg-muted/50">
          Edit
        </button>
        <button onClick={onToggle} className="rounded border px-3 py-1 text-xs hover:bg-muted/50">
          {a.is_active === 1 ? "Deactivate" : "Activate"}
        </button>
        <button onClick={onDelete} className="rounded border border-red-200 px-3 py-1 text-xs text-red-600 hover:bg-red-50">
          Delete
        </button>
      </div>
    </div>
  );
}

function EditModal({
  announcement,
  onClose,
  onSaved,
}: {
  announcement: Announcement | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [title, setTitle] = useState(announcement?.title ?? "");
  const [body, setBody] = useState(announcement?.body ?? "");
  const [expiresAt, setExpiresAt] = useState(announcement?.expires_at?.slice(0, 10) ?? "");
  const [isActive, setIsActive] = useState(announcement ? announcement.is_active === 1 : true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const valid = title.trim().length >= 3 && body.trim().length >= 10;

  async function save() {
    setSubmitting(true);
    setError("");
    // Date-only input → store end-of-day so it stays visible through that date.
    const expiry = expiresAt ? `${expiresAt} 23:59:59` : null;
    const payload = announcement
      ? { title, body, isActive, expiresAt: expiry }
      : { title, body, expiresAt: expiry };
    const resp = await fetch(announcement ? `/api/announcements/${announcement.id}` : "/api/announcements", {
      method: announcement ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSubmitting(false);
    if (resp.ok) {
      onSaved(announcement ? "Announcement updated." : "Announcement published.");
      return;
    }
    const data = await resp.json().catch(() => ({}));
    setError(data?.error?.message ?? "Failed to save announcement.");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md space-y-3 rounded-lg bg-white p-5 shadow-xl">
        <h4 className="text-sm font-semibold text-slate-700">
          {announcement ? "Edit announcement" : "New announcement"}
        </h4>
        <div>
          <input
            className="w-full rounded border p-2 text-sm"
            placeholder="Title (min 3 characters)"
            maxLength={80}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-slate-400">{title.length}/80</p>
        </div>
        <div>
          <textarea
            className="h-28 w-full rounded border p-2 text-sm"
            placeholder="Body (min 10 characters)"
            maxLength={500}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-slate-400">{body.length}/500</p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex-1 text-xs text-muted-foreground">
            Expiry (optional)
            <input
              type="date"
              className="mt-1 w-full rounded border p-2 text-sm"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
          </label>
          {announcement && (
            <label className="flex items-center gap-2 pt-4 text-sm">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              Active
            </label>
          )}
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded border px-3 py-2 text-sm hover:bg-muted/50">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={!valid || submitting}
            className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
