"use client";

import { useState } from "react";
import { BarChart3, ChevronLeft, ChevronRight, Inbox, Settings2 } from "lucide-react";

export type NavKey = "analytics" | "queue" | "admin";

const NAV: { key: NavKey; label: string; icon: typeof Inbox; adminOnly?: boolean }[] = [
  { key: "analytics", label: "Analytics", icon: BarChart3 },
  { key: "queue", label: "Ticket Queue", icon: Inbox },
  { key: "admin", label: "Administration", icon: Settings2, adminOnly: true },
];

/**
 * Collapsible left navigation (UI_REVAMP_v2 §A3). Desktop: w-56 expanded /
 * w-14 collapsed with a 200ms width transition; ≤768px it renders as a fixed
 * bottom tab bar instead. Controls the dashboard's existing tab state — the
 * active view is still owned by the page.
 */
export default function Sidebar({
  active,
  role,
  onSelect,
}: {
  active: NavKey;
  role: string;
  onSelect: (key: NavKey) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const items = NAV.filter((n) => !n.adminOnly || role === "admin");

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={`sticky top-14 hidden h-[calc(100vh-3.5rem)] shrink-0 flex-col border-r bg-white transition-[width] duration-200 ease-in-out md:flex ${
          collapsed ? "w-14" : "w-56"
        }`}
      >
        <nav className="flex-1 space-y-1 py-3">
          {items.map(({ key, label, icon: Icon }) => {
            const isActive = active === key;
            return (
              <button
                key={key}
                onClick={() => onSelect(key)}
                title={collapsed ? label : undefined}
                className={`flex w-full items-center gap-3 border-l-[3px] px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "border-[#028090] bg-[#E8F6F8]/60 font-semibold text-[#028090]"
                    : "border-transparent text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon className={`h-5 w-5 shrink-0 ${isActive ? "text-[#028090]" : "text-slate-400"}`} />
                {!collapsed && <span className="truncate">{label}</span>}
              </button>
            );
          })}
        </nav>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="m-2 flex items-center justify-center rounded-md border py-2 text-slate-400 hover:bg-slate-100"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </aside>

      {/* Mobile bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-white md:hidden">
        {items.map(({ key, label, icon: Icon }) => {
          const isActive = active === key;
          return (
            <button
              key={key}
              onClick={() => onSelect(key)}
              className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${
                isActive ? "font-semibold text-[#028090]" : "text-slate-500"
              }`}
            >
              <Icon className="h-5 w-5" />
              {label.split(" ")[0]}
            </button>
          );
        })}
      </nav>
    </>
  );
}
