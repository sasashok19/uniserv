"use client";

import { useEffect, useState } from "react";
import { Megaphone, X } from "lucide-react";

import type { Announcement } from "./AnnouncementBell";

const DISMISS_KEY = "announcementBannerDismissed";

/**
 * Dismissible banner under the topbar showing the most recent active
 * announcement (UI_REVAMP_v2 Feature C). Dismissal is per-session — it
 * reappears on next login.
 */
export default function AnnouncementBanner() {
  const [latest, setLatest] = useState<Announcement | null>(null);
  const [dismissedId, setDismissedId] = useState<string | null>(null);

  useEffect(() => {
    try {
      setDismissedId(sessionStorage.getItem(DISMISS_KEY));
    } catch {
      /* private mode */
    }
    fetch("/api/announcements?activeOnly=true")
      .then((r) => r.json())
      .then((d) => {
        const list: Announcement[] = Array.isArray(d.announcements) ? d.announcements : [];
        setLatest(list[0] ?? null);
      })
      .catch(() => setLatest(null));
  }, []);

  if (!latest || latest.id === dismissedId) return null;

  return (
    <div className="flex items-center gap-3 bg-[#028090] px-4 py-2 text-sm text-white">
      <Megaphone className="h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1 truncate">
        <span className="font-semibold">{latest.title}</span>
        <span className="mx-2 opacity-60">—</span>
        <span className="opacity-90">{latest.body}</span>
      </p>
      <button
        onClick={() => {
          try {
            sessionStorage.setItem(DISMISS_KEY, latest.id);
          } catch {
            /* private mode */
          }
          setDismissedId(latest.id);
        }}
        className="shrink-0 rounded p-1 hover:bg-white/20"
        aria-label="Dismiss announcement"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
