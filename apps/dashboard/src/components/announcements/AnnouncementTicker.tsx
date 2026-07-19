"use client";

import { useEffect, useState } from "react";
import { Megaphone } from "lucide-react";

/**
 * Login-page marquee of active announcement titles (public endpoint — no
 * auth). Hidden entirely when there are none. CSS-only animation, pauses on
 * hover.
 */
export default function AnnouncementTicker() {
  const [titles, setTitles] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/public/announcements")
      .then((r) => r.json())
      .then((d) => {
        const list = Array.isArray(d.announcements) ? d.announcements : [];
        setTitles(list.map((a: { title: string }) => a.title).filter(Boolean));
      })
      .catch(() => setTitles([]));
  }, []);

  if (titles.length === 0) return null;
  const line = titles.join("   •   ");

  return (
    <div className="flex items-center gap-2 overflow-hidden rounded-lg bg-white/10 px-3 py-2 text-sm text-white">
      <Megaphone className="h-4 w-4 shrink-0 opacity-80" />
      <div className="ticker-window min-w-0 flex-1 overflow-hidden whitespace-nowrap">
        <span className="ticker-content inline-block pl-[100%]">{line}</span>
      </div>
      <style jsx>{`
        .ticker-content {
          animation: ticker-scroll 25s linear infinite;
        }
        .ticker-window:hover .ticker-content {
          animation-play-state: paused;
        }
        @keyframes ticker-scroll {
          from {
            transform: translateX(0);
          }
          to {
            transform: translateX(-100%);
          }
        }
      `}</style>
    </div>
  );
}
