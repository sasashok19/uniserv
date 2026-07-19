"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { priorityBadgeClass, statusBadgeClass } from "@/lib/badges";

type Note = { authorType: string; authorLabel: string; content: string; createdAt: string };
type Message = { direction: string; authorType: string; content: string; createdAt: string };
type TicketDetail = {
  id: string;
  ticketNumber: string;
  status: string;
  resolution: string | null;
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
  notes: Note[];
  messages: Message[];
};

type Agent = { id: string; name: string };

type AuditEvent = {
  eventType: string;
  actorType: string | null;
  actorName: string | null;
  assignedToName?: string;
  createdAt: string;
};

/** Human-readable audit line: "Status → resolved — by Admin User". */
function describeEvent(e: AuditEvent): string {
  const by = e.actorName ? ` — by ${e.actorName}` : e.actorType === "system" ? " — system" : "";
  if (e.eventType === "ticket.created") return `Ticket created${by}`;
  if (e.eventType.startsWith("status.")) return `Status → ${e.eventType.slice(7).replace(/_/g, " ")}${by}`;
  if (e.eventType === "ticket.assigned") return `Assigned to ${e.assignedToName ?? "an agent"}${by}`;
  if (e.eventType === "ticket.unassigned") return `Unassigned${by}`;
  if (e.eventType === "ticket.archived") return `Archived${by}`;
  if (e.eventType === "ticket.auto_closed") return `Auto-closed (no citizen response)${by}`;
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

/** Mirrors db-writer's MANDATORY_NOTE_TRANSITIONS — UI hint only, server enforces. */
const MANDATORY_NOTE_TRANSITIONS = new Set(["in_progress->resolved", "resolved->closed", "closed->reopened"]);

const STATUS_LABEL = (s: string) => s.replace(/_/g, " ");

function InfoField({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <span className="text-xs text-muted-foreground">{label}</span>
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

  if (loading) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  if (!ticket) return <p className="p-6 text-sm">Ticket not found.</p>;

  const nextStatuses = NEXT_STATUSES[ticket.status] ?? [];

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
      } else if (ticket.channelOrigin === "email") {
        if (data.emailSent) {
          setSendState("sent");
          setSendResult("Sent — the citizen has been emailed.");
        } else {
          setSendState("failed");
          setSendResult(`Recorded on the ticket, but the email FAILED: ${data.emailError ?? "unknown reason"}.`);
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
    const key = `${ticket?.status}->${toStatus}`;
    if (MANDATORY_NOTE_TRANSITIONS.has(key) && noteText.trim().length < 20) {
      setStatusMsg("This transition requires a note of at least 20 characters — type it in the note box.");
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
      <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
        ← Back to ticket queue
      </Link>

      <div className="mt-3 mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold text-indigo-700">{ticket.ticketNumber}</h1>
        <span className={statusBadgeClass(ticket.status)}>{STATUS_LABEL(ticket.status)}</span>
      </div>

      {statusMsg && <p className="mb-4 rounded border bg-white p-2 text-sm shadow-sm">{statusMsg}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* LEFT: conversation (top) + audit trail (bottom), equal share, own scrollbars. */}
        <div className="space-y-6">
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Conversation</h2>
            {ticket.messages.length === 0 ? (
              <p className="text-sm text-muted-foreground">No messages yet.</p>
            ) : (
              <ul className="max-h-[38vh] space-y-2 overflow-y-auto pr-1">
                {ticket.messages.map((m, i) => (
                  <li
                    key={i}
                    className={`rounded-lg border p-3 text-sm ${m.direction === "outbound" ? "bg-indigo-50" : "bg-slate-50"}`}
                  >
                    <div className="mb-1 text-xs text-muted-foreground">
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
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Audit trail</h2>
            {events.length === 0 ? (
              <p className="text-sm text-muted-foreground">No audit events recorded.</p>
            ) : (
              <ul className="max-h-[38vh] space-y-1 overflow-y-auto pr-1">
                {[...events].reverse().map((e, i) => (
                  <li key={i} className="flex items-baseline gap-2 border-b py-1.5 text-sm last:border-b-0">
                    <span className="whitespace-nowrap text-xs text-muted-foreground">{e.createdAt}</span>
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
            <h3 className="mb-3 text-sm font-semibold text-slate-700">Citizen details</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <InfoField label="Name" value={ticket.citizenName} />
              <InfoField label="Email" value={ticket.citizenEmail} />
              <InfoField label="Phone" value={ticket.citizenPhone} />
              <InfoField label="Service/Customer ID" value={ticket.serviceId} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 sm:grid-cols-4">
              <InfoField label="Category" value={ticket.category} />
              <div>
                <span className="text-xs text-muted-foreground">Priority</span>
                <div>
                  {ticket.priorityLabel ? (
                    <span className={priorityBadgeClass(ticket.priorityLabel)}>{ticket.priorityLabel}</span>
                  ) : (
                    "—"
                  )}
                </div>
              </div>
              <InfoField label="Channel" value={ticket.channelOrigin} />
              <div>
                <span className="text-xs text-muted-foreground">Assigned to</span>
                {ticket.canAssign ? (
                  <select
                    className="mt-0.5 w-full rounded border p-1 text-sm"
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

          {/* Status transition with the internal note inline: type a note (grey
              placeholder), click a transition — the note rides along. */}
          {nextStatuses.length > 0 && (
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <h3 className="mb-2 text-sm font-semibold text-slate-700">Status &amp; internal note</h3>
              <textarea
                className="mb-2 w-full rounded border p-2 text-sm placeholder:text-slate-400"
                placeholder="Add internal note (visible to your team only; some transitions require min 20 characters)"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={3}
              />
              <div className="flex flex-wrap items-center gap-2">
                {nextStatuses.map((s) => (
                  <button
                    key={s}
                    onClick={() => transition(s)}
                    disabled={transitioning !== null}
                    className="inline-flex items-center gap-1.5 rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {transitioning === s && <Loader2 className="h-4 w-4 animate-spin" />}
                    Move to {STATUS_LABEL(s)}
                  </button>
                ))}
                <button
                  onClick={saveNoteOnly}
                  disabled={savingNote || !noteText.trim()}
                  className="ml-auto text-xs text-indigo-600 hover:underline disabled:opacity-40"
                  title="Save the note without changing status"
                >
                  {savingNote ? "Saving…" : "Save note only"}
                </button>
              </div>
            </div>
          )}

          {/* Follow-up to the citizen, with explicit delivery feedback. */}
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">
              Ask a follow-up / update the customer
            </h2>
            <form onSubmit={sendReply} className="space-y-2">
              <textarea
                className="w-full rounded border p-2 text-sm placeholder:text-slate-400"
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
                  className="inline-flex items-center gap-1.5 rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
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
                <p className="text-xs text-muted-foreground">
                  Tip: after asking a question, move the ticket to &quot;pending customer&quot; above so the
                  queue shows you are waiting on the citizen.
                </p>
              )}
            </form>
          </section>

          {/* Note history — reference material, mirrors the conversation panel. */}
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Internal notes</h2>
            {ticket.notes.length === 0 ? (
              <p className="text-sm text-muted-foreground">No notes yet.</p>
            ) : (
              <ul className="max-h-[30vh] space-y-2 overflow-y-auto pr-1">
                {ticket.notes.map((n, i) => (
                  <li key={i} className="rounded-lg border bg-slate-50 p-3 text-sm">
                    <div className="mb-1 text-xs text-muted-foreground">
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
