/**
 * UniServe design tokens (UI_REVAMP_v2 §A1) — the single source of truth for
 * brand colours and per-domain (priority/status/channel/identity) palettes.
 * `badges.ts` and components read from here; do not duplicate hex values.
 */
export const tokens = {
  colors: {
    navy: "#0D1B2A",
    navyMid: "#1B3A52",
    teal: "#028090",
    tealLight: "#02C39A",
    tealXL: "#E8F6F8",
    gold: "#F4A261",
    goldLight: "#FFF3E8",
    coral: "#E07B54",
    coralLight: "#FFF0EB",
    white: "#FFFFFF",
    offWhite: "#F8FAFC",
    slate: "#F1F5F9",
    border: "#E2E8F0",
    grey: "#64748B",
    black: "#0F172A",
    success: "#1A936F",
    warning: "#F59E0B",
    danger: "#DC2626",
    info: "#0284C7",
  },
  priority: {
    critical: { bg: "#FEF2F2", text: "#DC2626", border: "#FECACA", dot: "#DC2626" },
    high: { bg: "#FFF7ED", text: "#EA580C", border: "#FED7AA", dot: "#EA580C" },
    medium: { bg: "#FEFCE8", text: "#CA8A04", border: "#FEF08A", dot: "#CA8A04" },
    low: { bg: "#F0FDF4", text: "#16A34A", border: "#BBF7D0", dot: "#16A34A" },
  },
  status: {
    open: { bg: "#EFF6FF", text: "#1D4ED8", label: "Open" },
    assigned: { bg: "#F5F3FF", text: "#7C3AED", label: "Assigned" },
    in_progress: { bg: "#FFF7ED", text: "#C2410C", label: "In Progress" },
    resolved: { bg: "#F0FDF4", text: "#15803D", label: "Resolved" },
    closed: { bg: "#F8FAFC", text: "#475569", label: "Closed" },
    reopened: { bg: "#FFF1F2", text: "#BE123C", label: "Reopened" },
  },
  channel: {
    email: { color: "#0284C7", icon: "Mail" },
    whatsapp: { color: "#16A34A", icon: "MessageCircle" },
  },
  identityStatus: {
    confirmed: { bg: "#F0FDF4", text: "#15803D", label: "Confirmed" },
    pending: { bg: "#FFF7ED", text: "#C2410C", label: "Needs identity" },
    anonymous: { bg: "#F5F3FF", text: "#7C3AED", label: "Anonymous" },
  },
} as const;

export type PriorityKey = keyof typeof tokens.priority;
export type StatusKey = keyof typeof tokens.status;
export type IdentityStatusKey = keyof typeof tokens.identityStatus;
