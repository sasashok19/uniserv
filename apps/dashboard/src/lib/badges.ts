/**
 * Shared colour mapping for status/priority/role/identity badges (Feature 12/15).
 * Colours are sourced from `design-tokens.ts` (the single source of truth) via
 * inline styles — Tailwind's JIT compiler can't see dynamic arbitrary-value
 * classes at build time, so `style={{...}}` is the correct, safe way to apply
 * token colours rather than string-templating `bg-[...]` class names.
 */
import type { CSSProperties } from "react";
import { tokens } from "@/lib/design-tokens";

export const BASE = "rounded-full px-2.5 py-0.5 text-xs font-medium capitalize";

function tokenStyle(entry: { bg: string; text: string } | undefined): CSSProperties {
  if (!entry) return { backgroundColor: "#F1F5F9", color: "#64748B" };
  return { backgroundColor: entry.bg, color: entry.text };
}

export function statusBadgeStyle(status: string | null | undefined): CSSProperties {
  return tokenStyle((tokens.status as Record<string, { bg: string; text: string }>)[status ?? ""]);
}

export function priorityBadgeStyle(label: string | null | undefined): CSSProperties {
  return tokenStyle((tokens.priority as Record<string, { bg: string; text: string }>)[label ?? ""]);
}

export function identityBadgeStyle(status: string | null | undefined): CSSProperties {
  return tokenStyle((tokens.identityStatus as Record<string, { bg: string; text: string }>)[status ?? ""]);
}

/**
 * Role/active badges have no design-token equivalent yet (design-tokens.ts
 * models status/priority/channel/identityStatus only) — kept as Tailwind
 * classes, aligned to the same navy/teal/slate the Topbar role pill already
 * uses so the two don't visually disagree.
 */
export function roleBadgeClass(role: string | null | undefined): string {
  switch (role) {
    case "admin":
      return `${BASE} bg-[#0D1B2A]/10 text-[#0D1B2A]`;
    case "lead":
      return `${BASE} bg-[#028090]/10 text-[#026670]`;
    case "agent":
      return `${BASE} bg-slate-200 text-slate-600`;
    default:
      return `${BASE} bg-slate-100 text-slate-500`;
  }
}

export function activeBadgeClass(active: boolean): string {
  return active ? `${BASE} bg-green-100 text-green-700` : `${BASE} bg-slate-200 text-slate-500`;
}
