"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, MessageCircle, XCircle } from "lucide-react";

import { BASE as BADGE_BASE, priorityBadgeStyle, statusBadgeStyle } from "@/lib/badges";

/** Left-border accent per author type — lets a reviewer scanning a thread tell
 * AI-drafted vs. citizen-written vs. agent-written content apart at a glance
 * (matters for audit/QA in a government context). */
const AUTHOR_BORDER: Record<string, string> = {
  ai: "border-l-4 border-l-brand-teal",
  agent: "border-l-4 border-l-slate-300",
  system: "border-l-4 border-l-slate-300",
  user: "border-l-4 border-l-blue-300",
};

type Note = { authorType: string; authorLabel: string; content: string; createdAt: string };
type Message = { direction: string; authorType: string; content: string; createdAt: string };
type TicketDetail = {
  id: string;
  ticketNumber: string;
  status: string;
  resolution: string | null;
  /** Feature 23: the citizen's own complaint in one line, derived by ai-core
   * from the message that opened the ticket and re-derived as they reply.
   * Null on a ticket that predates the field or has had no inbound message. */
  chiefComplaint: string | null;
  category: string | null;
  channelOrigin: string;
  identityId: string | null;
  citizenName: string | null;
  citizenEmail: string | null;
  citizenPhone: string | null;
  serviceId: string | null;
  priorityLabel: string | null;
  assignedTo: string | null;
  assignedToName: string | null;
  canAssign: boolean;
  canCancel: boolean;
  notes: Note[];
  messages: Message[];
};

type Agent = { id: string; name: string };

type AuditEvent = {
  eventType: string;
  actorType: string | null;
  actorName: string | null;
  assignedToName?: string;
  duplicateOfId?: string;
  duplicateOfNumber?: string;
  mergedFromNumber?: string;
  reason?: string;
  createdAt: string;
};

/**
 * Feature 22: routing can flag "this might be a duplicate of TKT-xxxxx" and
 * the AI asks the citizen — but citizens frequently never answer, and the
 * flag would then sit on the ticket with nobody able to clear it. The audit
 * trail is the source of truth: a `possible_duplicate` counts as outstanding
 * only while no later event has settled it.
 */
function outstandingDuplicate(events: AuditEvent[]): AuditEvent | null {
  let pending: AuditEvent | null = null;
  for (const e of events) {
    if (e.eventType === "ticket.possible_duplicate") pending = e;
    else if (e.eventType === "ticket.duplicate_confirmed" || e.eventType === "ticket.duplicate_dismissed") {
      pending = null;
    }
  }
  return pending;
}

/** Human-readable audit line: "Status → resolved — by Admin User". */
function describeEvent(e: AuditEvent): string {
  const by = e.actorName ? ` — by ${e.actorName}` : e.actorType === "system" ? " — system" : "";
  if (e.eventType === "ticket.created") return `Ticket created${by}`;
  if (e.eventType.startsWith("status.")) return `Status → ${e.eventType.slice(7).replace(/_/g, " ")}${by}`;
  if (e.eventType === "ticket.assigned") return `Assigned to ${e.assignedToName ?? "an agent"}${by}`;
  if (e.eventType === "ticket.unassigned") return `Unassigned${by}`;
  if (e.eventType === "ticket.archived") return `Archived${by}`;
  if (e.eventType === "ticket.auto_closed") return `Auto-closed (no citizen response)${by}`;
  if (e.eventType === "ticket.possible_duplicate") {
    return `Flagged as a possible duplicate of ${e.duplicateOfNumber ?? "another ticket"}${by}`;
  }
  if (e.eventType === "ticket.duplicate_confirmed") {
    return `Confirmed duplicate of ${e.duplicateOfNumber ?? "another ticket"}${by}`;
  }
  if (e.eventType === "ticket.duplicate_dismissed") return `Not a duplicate${by}`;
  if (e.eventType === "ticket.duplicate_merged") {
    return `${e.mergedFromNumber ?? "Another ticket"} merged into this one as a duplicate${by}`;
  }
  return `${e.eventType}${by}`;
}

/**
 * Allowed next statuses per current status. `in_progress` forks: park the
 * ticket as "pending customer" while awaiting the citizen's answer (paired
 * with the follow-up box below), or resolve it.
 */
const NEXT_STATUSES: Record<string, string[]> = {
  open: ["assigned"],
  assigned: ["in_progress"],
  in_progress: ["pending_customer", "resolved"],
  pending_customer: ["in_progress", "resolved"],
  resolved: ["closed"],
  closed: ["reopened"],
  reopened: ["in_progress"],
};

/**
 * Feature 21: cancelling is available from any non-terminal status rather than
 * as one more step in the lifecycle — it says "this was never real work"
 * (duplicate, test row, withdrawn complaint), which can become true at any
 * point. Offered only when the server says this role may do it
 * (`canCancel`, admin-only) and always requires a note.
 */
const CANCELLABLE_FROM = new Set(["open", "assigned", "in_progress", "pending_customer", "resolved", "reopened"]);

/** Mirrors db-writer's MANDATORY_NOTE_TRANSITIONS — UI hint only, server enforces. */
const MANDATORY_NOTE_TRANSITIONS = new Set(["in_progress->resolved", "resolved->closed", "closed->reopened"]);

/** True when this transition needs a note — any cancel, plus the pairs above. */
function needsNote(from: string, to: string): boolean {
  return to === "cancelled" || MANDATORY_NOTE_TRANSITIONS.has(`${from}->${to}`);
}

const STATUS_LABEL = (s: string) => s.replace(/_/g, " ");

function InfoField({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <span className="text-xs text-slate-600">{label}</span>
      <div className="text-sm">{value || "—"}</div>
    </div>
  );
}

export default function TicketDetailPage({ params }: { params: { id: string } }) {
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");
  const [replyText, setReplyText] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [assigning, setAssigning] = useState(false);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [transitioning, setTransitioning] = useState<string | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [resolvingDuplicate, setResolvingDuplicate] = useState(false);
  // Follow-up send lifecycle: the agent must SEE whether the message reached
  // the citizen or failed (e.g. connection issue) — busy spinner, then an
  // explicit sent/failed confirmation.
  const [sendState, setSendState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const [sendResult, setSendResult] = useState("");

  async function load() {
    setLoading(true);
    const resp = await fetch(`/api/tickets/${params.id}`);
    const data = await resp.json();
    setTicket(resp.ok ? data : null);
    setLoading(false);
    if (resp.ok && data.canAssign) {
      const agentsResp = await fetch("/api/analytics/agents-directory");
      const agentsData = await agentsResp.json().catch(() => ({}));
      setAgents(agentsData.agents ?? []);
    }
    // Audit trail (creation, assignments, status transitions) — best-effort.
    fetch(`/api/tickets/${params.id}/events`)
      .then((r) => r.json())
      .then((d) => setEvents(Array.isArray(d.events) ? d.events : []))
      .catch(() => setEvents([]));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function assign(agentId: string) {
    setAssigning(true);
    const resp = await fetch(`/api/tickets/${params.id}/assign`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignedTo: agentId || null }),
    });
    setAssigning(false);
    setStatusMsg(resp.ok ? "Assignment updated." : "Failed to update assignment.");
    await load();
  }

  if (loading) return <p className="p-6 text-sm text-slate-500">Loading…</p>;
  if (!ticket) return <p className="p-6 text-sm">Ticket not found.</p>;

  const nextStatuses = NEXT_STATUSES[ticket.status] ?? [];
  // Cancel is not part of the lifecycle chain, so it's appended rather than
  // listed in NEXT_STATUSES — available from any non-terminal status, and only
  // to a role the server has already said may do it.
  const cancellable = ticket.canCancel && CANCELLABLE_FROM.has(ticket.status);
  const statusActions = cancellable ? [...nextStatuses, "cancelled"] : nextStatuses;
  const pendingDuplicate = outstandingDuplicate(events);

  async function resolveDuplicate(isDuplicate: boolean) {
    if (!pendingDuplicate) return;
    setResolvingDuplicate(true);
    const resp = await fetch(`/api/tickets/${params.id}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isDuplicate, duplicateOfId: pendingDuplicate.duplicateOfId }),
    });
    const data = await resp.json().catch(() => ({}));
    setResolvingDuplicate(false);
    setStatusMsg(
      resp.ok
        ? isDuplicate
          ? `Merged into ${pendingDuplicate.duplicateOfNumber ?? "the original ticket"}.`
          : "Marked as a separate complaint."
        : data?.error?.message ?? "Could not update the duplicate status.",
    );
    await load();
  }

  /** Save the typed note WITHOUT a status change (small affordance, no big button). */
  async function saveNoteOnly() {
    if (!noteText.trim()) return;
    setSavingNote(true);
    const resp = await fetch(`/api/tickets/${params.id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: noteText }),
    });
    setSavingNote(false);
    setStatusMsg(resp.ok ? "Note added." : "Failed to add note.");
    if (resp.ok) setNoteText("");
    await load();
  }

  async function sendReply(e: React.FormEvent) {
    e.preventDefault();
    if (!replyText.trim() || !ticket || sendState === "sending") return;
    setSendState("sending");
    setSendResult("");
    try {
      const resp = await fetch(`/api/tickets/${params.id}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: replyText }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setSendState("failed");
        setSendResult(data?.error?.message ?? "Failed to send — please try again.");
      } else if (ticket.channelOrigin === "email" || ticket.channelOrigin === "whatsapp") {
        const via = ticket.channelOrigin === "email" ? "emailed" : "messaged on WhatsApp";
        if (data.sent) {
          setSendState("sent");
          setSendResult(`Sent — the citizen has been ${via}.`);
        } else {
          setSendState("failed");
          setSendResult(`Recorded on the ticket, but the send FAILED: ${data.sendError ?? "unknown reason"}.`);
        }
      } else {
        setSendState("sent");
        setSendResult(`Recorded (no outbound send wired for "${ticket.channelOrigin}" yet).`);
      }
      if (resp.ok) setReplyText("");
    } catch {
      setSendState("failed");
      setSendResult("Network error — the message was NOT sent. Check your connection and retry.");
    }
    await load();
  }

  async function transition(toStatus: string) {
    if (needsNote(ticket?.status ?? "", toStatus) && noteText.trim().length < 20) {
      setStatusMsg("This transition requires a note of at least 20 characters — type it in the note box.");
      return;
    }
    if (toStatus === "cancelled" &&
        !window.confirm(
          `Cancel ${ticket?.ticketNumber}? This marks it as never having been real work — it will not ` +
          `count as resolved, and it cannot be reopened. Your note will be recorded against it.`)) {
      return;
    }
    setTransitioning(toStatus);
    const resp = await fetch(`/api/tickets/${params.id}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toStatus, note: noteText.trim() || undefined }),
    });
    const data = await resp.json().catch(() => ({}));
    setTransitioning(null);
    setStatusMsg(resp.ok ? `Status changed to ${STATUS_LABEL(toStatus)}.` : (data?.error?.message ?? "Transition failed."));
    if (resp.ok) setNoteText("");
    await load();
  }

  return (
    <main className="mx-auto max-w-7xl p-6">
      <Link href="/dashboard" className="text-sm text-slate-500 hover:text-brand-teal hover:underline">
        ← Back to ticket queue
      </Link>

      <div className="mt-3 flex items-center justify-between">
        <h1 className="text-xl font-bold text-brand-teal">{ticket.ticketNumber}</h1>
        <span className={BADGE_BASE} style={statusBadgeStyle(ticket.status)}>
          {STATUS_LABEL(ticket.status)}
        </span>
      </div>

      {/* Feature 23: the chief complaint sits with the ticket number rather than
          among the metadata fields — it is the ticket's subject line, and an
          agent opening this page should not have to find it. Rendered even when
          empty so the page never silently omits it: a blank one means the
          citizen's first message hasn't been processed, which is itself worth
          seeing. */}
      <p className="mb-6 mt-1 text-base text-slate-700">
        <span className="mr-2 text-xs uppercase tracking-wide text-slate-500">Chief complaint</span>
        {ticket.chiefComplaint ? (
          <span className="font-medium">{ticket.chiefComplaint}</span>
        ) : (
          <span className="italic text-slate-400">Not yet determined</span>
        )}
      </p>

      {statusMsg && <p className="mb-4 rounded border bg-white p-2 text-sm shadow-sm">{statusMsg}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* LEFT: conversation (top) + audit trail (bottom), equal share, own scrollbars. */}
        <div className="space-y-6">
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-base font-semibold text-slate-800">
              Conversation <span className="text-xs font-normal text-slate-500">(newest first)</span>
            </h2>
            {ticket.messages.length === 0 ? (
              <p className="text-sm text-slate-500">No messages yet.</p>
            ) : (
              /* Newest first (user-requested), matching the audit trail below:
                 an agent opening a ticket wants the latest exchange, not to
                 scroll a long thread to reach it. The API returns the timeline
                 oldest-first, so it is reversed here rather than server-side —
                 chronological order is the correct storage order and the CSV
                 export reads it that way. */
              <ul className="max-h-[38vh] space-y-2 overflow-y-auto pr-1">
                {[...ticket.messages].reverse().map((m, i) => (
                  <li
                    key={i}
                    className={`rounded-lg border bg-slate-50 p-3 text-sm ${AUTHOR_BORDER[m.authorType] ?? "border-l-4 border-l-slate-300"}`}
                  >
                    <div className="mb-1 text-xs text-slate-600">
                      {m.direction === "outbound" ? "Sent" : "Received"} · {m.authorType} · {m.createdAt}
                    </div>
                    {m.content}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Audit trail — newest first. */}
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-base font-semibold text-slate-800">Audit trail</h2>
            {events.length === 0 ? (
              <p className="text-sm text-slate-500">No audit events recorded.</p>
            ) : (
              <ul className="max-h-[38vh] space-y-1 overflow-y-auto pr-1">
                {[...events].reverse().map((e, i) => (
                  <li key={i} className="flex items-baseline gap-2 border-b py-1.5 text-sm last:border-b-0">
                    <span className="whitespace-nowrap text-xs text-slate-600">{e.createdAt}</span>
                    <span className="min-w-0 flex-1 text-slate-700">{describeEvent(e)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* RIGHT: everything the agent acts on. */}
        <div className="space-y-6">
          <div className="rounded-lg border bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-base font-semibold text-slate-800">Citizen details</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <InfoField label="Name" value={ticket.citizenName} />
              <InfoField label="Email" value={ticket.citizenEmail} />
              <InfoField label="Phone" value={ticket.citizenPhone} />
              <InfoField label="Service/Customer ID" value={ticket.serviceId} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 sm:grid-cols-4">
              <InfoField label="Category" value={ticket.category} />
              <div>
                <span className="text-xs text-slate-600">Priority</span>
                <div>
                  {ticket.priorityLabel ? (
                    <span className={BADGE_BASE} style={priorityBadgeStyle(ticket.priorityLabel)}>
                      {ticket.priorityLabel}
                    </span>
                  ) : (
                    "—"
                  )}
                </div>
              </div>
              <InfoField label="Channel" value={ticket.channelOrigin} />
              <div>
                <span className="text-xs text-slate-600">Assigned to</span>
                {ticket.canAssign ? (
                  <select
                    className="mt-0.5 w-full rounded border p-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                    value={ticket.assignedTo ?? ""}
                    disabled={assigning}
                    onChange={(e) => assign(e.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="text-sm">{ticket.assignedToName ?? "Unassigned"}</div>
                )}
              </div>
            </div>
          </div>

          {/* Feature 22: an unanswered duplicate question. Shown until an agent
              settles it, because the citizen often never will. */}
          {pendingDuplicate && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 shadow-sm">
              <h3 className="text-base font-semibold text-amber-900">Possible duplicate</h3>
              <p className="mt-1 text-sm text-amber-900">
                This may be the same complaint as{" "}
                <span className="font-semibold">{pendingDuplicate.duplicateOfNumber ?? "another open ticket"}</span>
                {pendingDuplicate.reason ? ` — ${pendingDuplicate.reason}` : ""}. The citizen was asked and
                hasn&apos;t settled it.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  onClick={() => resolveDuplicate(true)}
                  disabled={resolvingDuplicate}
                  className="inline-flex items-center gap-1.5 rounded bg-amber-700 px-3 py-2 text-sm font-medium text-white hover:bg-amber-800 active:scale-[0.97] disabled:opacity-50"
                >
                  {resolvingDuplicate && <Loader2 className="h-4 w-4 animate-spin" />}
                  Yes — merge into {pendingDuplicate.duplicateOfNumber ?? "it"}
                </button>
                <button
                  onClick={() => resolveDuplicate(false)}
                  disabled={resolvingDuplicate}
                  className="rounded border border-amber-400 bg-white px-3 py-2 text-sm font-medium text-amber-900 hover:bg-amber-100 active:scale-[0.97] disabled:opacity-50"
                >
                  No — separate complaint
                </button>
                {pendingDuplicate.duplicateOfId && (
                  <a
                    href={`/dashboard/tickets/${pendingDuplicate.duplicateOfId}`}
                    className="text-sm text-amber-900 underline hover:no-underline"
                  >
                    Open {pendingDuplicate.duplicateOfNumber ?? "the other ticket"}
                  </a>
                )}
              </div>
            </div>
          )}

          {/* Status transition with the internal note inline: type a note (grey
              placeholder), click a transition — the note rides along. */}
          {statusActions.length > 0 && (
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <h3 className="mb-2 text-base font-semibold text-slate-800">Status &amp; internal note</h3>
              <textarea
                className="mb-1 w-full rounded border p-2 text-sm placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                placeholder="Add internal note (visible to your team only; some transitions require min 20 characters)"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={3}
              />
              {statusActions.some((s) => needsNote(ticket.status, s)) && (
                <p className={`mb-2 text-xs ${noteText.trim().length < 20 ? "text-amber-600" : "text-emerald-600"}`}>
                  {noteText.trim().length}/20 characters — required for some transitions below
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {statusActions.map((s) => {
                  const noteRequired = needsNote(ticket.status, s);
                  const blocked = noteRequired && noteText.trim().length < 20;
                  // Cancel is destructive and off the lifecycle path, so it
                  // reads as such rather than sitting in the row of teal
                  // "Move to ..." buttons as if it were the next step.
                  const isCancel = s === "cancelled";
                  return (
                    <button
                      key={s}
                      onClick={() => transition(s)}
                      disabled={transitioning !== null || blocked}
                      title={blocked ? "Add a note of at least 20 characters first" : undefined}
                      className={
                        "inline-flex items-center gap-1.5 rounded px-3 py-2 text-sm font-medium transition-transform " +
                        "active:scale-[0.97] disabled:opacity-50 " +
                        (isCancel
                          ? "border border-red-300 bg-white text-red-700 hover:bg-red-50"
                          : "bg-brand-teal text-white hover:bg-brand-tealDark")
                      }
                    >
                      {transitioning === s && <Loader2 className="h-4 w-4 animate-spin" />}
                      {isCancel ? "Cancel ticket" : `Move to ${STATUS_LABEL(s)}`}
                      {noteRequired && (
                        <span
                          className={
                            "ml-1 rounded-full px-1.5 py-0.5 text-[10px] uppercase " +
                            (isCancel ? "bg-red-100 text-red-700" : "bg-white/20")
                          }
                        >
                          Note required
                        </span>
                      )}
                    </button>
                  );
                })}
                <button
                  onClick={saveNoteOnly}
                  disabled={savingNote || !noteText.trim()}
                  className="ml-auto text-xs text-brand-teal hover:underline disabled:opacity-40"
                  title="Save the note without changing status"
                >
                  {savingNote ? "Saving…" : "Save note only"}
                </button>
              </div>
            </div>
          )}

          {/* Follow-up to the citizen, with explicit delivery feedback. Teal
              accent + tag distinguish this citizen-facing box from the
              internal-only note box above — one gets emailed out, one never
              leaves the team. */}
          <section className="rounded-lg border border-l-4 border-l-brand-teal bg-white p-4 shadow-sm">
            <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-slate-800">
              Ask a follow-up / update the customer
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-tealTint px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-tealDark">
                <MessageCircle className="h-3 w-3" aria-hidden /> Citizen will see this
              </span>
            </h2>
            <form onSubmit={sendReply} className="space-y-2">
              <textarea
                className="w-full rounded border p-2 text-sm placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                placeholder={
                  ticket.channelOrigin === "email"
                    ? "Ask the citizen a question or share an update — this is emailed to them"
                    : "Ask a question or share an update (outbound send isn't wired for this channel yet)"
                }
                value={replyText}
                onChange={(e) => {
                  setReplyText(e.target.value);
                  if (sendState !== "sending") setSendState("idle");
                }}
                rows={3}
                disabled={sendState === "sending"}
              />
              <div className="flex items-center gap-3">
                <button
                  disabled={sendState === "sending" || !replyText.trim()}
                  className="inline-flex items-center gap-1.5 rounded bg-brand-teal px-4 py-2 text-sm font-medium text-white transition-transform hover:bg-brand-tealDark active:scale-[0.97] disabled:opacity-50"
                >
                  {sendState === "sending" && <Loader2 className="h-4 w-4 animate-spin" />}
                  {sendState === "sending" ? "Sending…" : "Send"}
                </button>
                {sendState === "sent" && (
                  <span className="inline-flex items-center gap-1 text-sm text-emerald-600">
                    <CheckCircle2 className="h-4 w-4" /> {sendResult}
                  </span>
                )}
                {sendState === "failed" && (
                  <span className="inline-flex items-center gap-1 text-sm text-red-600">
                    <XCircle className="h-4 w-4" /> {sendResult}
                  </span>
                )}
              </div>
              {ticket.status === "in_progress" && (
                <p className="text-xs text-slate-600">
                  Tip: after asking a question, move the ticket to &quot;pending customer&quot; above so the
                  queue shows you are waiting on the citizen.
                </p>
              )}
            </form>
          </section>

          {/* Note history — reference material, mirrors the conversation panel.
              Kept visually neutral/slate (no teal) to reinforce "internal only,
              stays inside the team" in contrast with the citizen-facing box above. */}
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-base font-semibold text-slate-800">Internal notes</h2>
            {ticket.notes.length === 0 ? (
              <p className="text-sm text-slate-500">No notes yet.</p>
            ) : (
              <ul className="max-h-[30vh] space-y-2 overflow-y-auto pr-1">
                {ticket.notes.map((n, i) => (
                  <li key={i} className={`rounded-lg border bg-slate-50 p-3 text-sm ${AUTHOR_BORDER[n.authorType] ?? "border-l-4 border-l-slate-300"}`}>
                    <div className="mb-1 text-xs text-slate-600">
                      {n.authorLabel} · {n.createdAt}
                    </div>
                    {n.content}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
