"use client";

import { useRouter } from "next/navigation";
import { LogOut, UserRound } from "lucide-react";

import AnnouncementBell from "@/components/announcements/AnnouncementBell";

const ROLE_PILL: Record<string, string> = {
  admin: "bg-[#0D1B2A] text-white",
  lead: "bg-[#028090] text-white",
  agent: "bg-slate-200 text-slate-700",
};

/**
 * Fixed dashboard topbar (UI_REVAMP_v2 §A3): wordmark + tenant, announcement
 * bell, identity (role pill — login only exposes the role, not the name) and
 * logout.
 */
export default function Topbar({ role }: { role: string }) {
  const router = useRouter();

  async function logout() {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      /* cookies cleared server-side; fall through to redirect regardless */
    }
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b bg-white px-4 shadow-sm">
      <div className="flex items-baseline gap-3">
        <span className="bg-gradient-to-r from-[#028090] to-[#02C39A] bg-clip-text text-xl font-extrabold tracking-tight text-transparent">
          UniServe
        </span>
        <span className="hidden text-xs uppercase tracking-widest text-slate-400 sm:inline">TNEB Demo</span>
      </div>

      <AnnouncementBell />

      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#E8F6F8] text-[#028090]">
          <UserRound className="h-4 w-4" />
        </span>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${ROLE_PILL[role] ?? ROLE_PILL.agent}`}
        >
          {role || "guest"}
        </span>
        <button
          onClick={logout}
          className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
        >
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">Logout</span>
        </button>
      </div>
    </header>
  );
}
