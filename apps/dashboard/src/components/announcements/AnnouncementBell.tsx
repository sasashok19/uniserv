"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";

export type Announcement = {
  id: string;
  title: string;
  body: string;
  created_by: string;
  is_active: number;
  expires_at: string | null;
  created_at: string;
};

const LAST_SEEN_KEY = "announcementLastSeen";
const POLL_MS = 5 * 60 * 1000;

/**
 * Topbar announcement bell (UI_REVAMP_v2 Feature C): unread badge counts active
 * announcements newer than the locally stored last-seen timestamp; the dropdown
 * shows the 3 most recent and "Mark all read" advances that timestamp.
 */
export default function AnnouncementBell() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<string>("");
  const wrapRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/api/announcements?activeOnly=true");
      const data = await resp.json().catch(() => ({}));
      setItems(Array.isArray(data.announcements) ? data.announcements : []);
    } catch {
      /* bell just stays empty */
    }
  }, []);

  useEffect(() => {
    try {
      setLastSeen(localStorage.getItem(LAST_SEEN_KEY) ?? "");
    } catch {
      /* private mode */
    }
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const unread = items.filter((a) => !lastSeen || a.created_at > lastSeen).length;

  function markAllRead() {
    const now = new Date().toISOString().slice(0, 19).replace("T", " ");
    try {
      localStorage.setItem(LAST_SEEN_KEY, now);
    } catch {
      /* private mode */
    }
    setLastSeen(now);
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-full p-2 text-slate-500 hover:bg-slate-100"
        aria-label="Announcements"
      >
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#E07B54] px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-lg border bg-white shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-semibold text-slate-700">Announcements</span>
            {items.length > 0 && (
              <button onClick={markAllRead} className="text-xs text-[#028090] hover:underline">
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No active announcements.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.slice(0, 3).map((a) => (
                <li key={a.id} className="border-b px-3 py-2 last:border-b-0">
                  <p className="text-sm font-medium text-slate-800">{a.title}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{a.body}</p>
                  <p className="mt-1 text-[10px] uppercase tracking-wide text-slate-400">{a.created_at}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
