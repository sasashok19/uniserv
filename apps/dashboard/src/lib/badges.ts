/** Shared colour mapping for status/priority/role badges (Feature 12/15). */

const BASE = "rounded-full px-2.5 py-0.5 text-xs font-medium capitalize";

export function statusBadgeClass(status: string | null | undefined): string {
  switch (status) {
    case "open":
      return `${BASE} bg-blue-100 text-blue-700`;
    case "assigned":
      return `${BASE} bg-indigo-100 text-indigo-700`;
    case "in_progress":
      return `${BASE} bg-amber-100 text-amber-700`;
    case "pending_customer":
      return `${BASE} bg-purple-100 text-purple-700`;
    case "resolved":
      return `${BASE} bg-green-100 text-green-700`;
    case "closed":
      return `${BASE} bg-slate-200 text-slate-600`;
    case "reopened":
      return `${BASE} bg-red-100 text-red-700`;
    default:
      return `${BASE} bg-slate-100 text-slate-500`;
  }
}

export function priorityBadgeClass(label: string | null | undefined): string {
  switch (label) {
    case "critical":
      return `${BASE} bg-red-100 text-red-700`;
    case "high":
      return `${BASE} bg-orange-100 text-orange-700`;
    case "medium":
      return `${BASE} bg-yellow-100 text-yellow-700`;
    case "low":
      return `${BASE} bg-green-100 text-green-700`;
    default:
      return `${BASE} bg-slate-100 text-slate-500`;
  }
}

export function identityBadgeClass(status: string | null | undefined): string {
  switch (status) {
    case "confirmed":
      return `${BASE} bg-green-100 text-green-700`;
    case "pending":
      return `${BASE} bg-amber-100 text-amber-700`;
    case "anonymous":
      return `${BASE} bg-slate-200 text-slate-600`;
    default:
      return `${BASE} bg-slate-100 text-slate-500`;
  }
}

export function roleBadgeClass(role: string | null | undefined): string {
  switch (role) {
    case "admin":
      return `${BASE} bg-purple-100 text-purple-700`;
    case "lead":
      return `${BASE} bg-blue-100 text-blue-700`;
    case "agent":
      return `${BASE} bg-slate-200 text-slate-600`;
    default:
      return `${BASE} bg-slate-100 text-slate-500`;
  }
}

export function activeBadgeClass(active: boolean): string {
  return active ? `${BASE} bg-green-100 text-green-700` : `${BASE} bg-slate-200 text-slate-500`;
}
