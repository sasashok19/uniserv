"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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

const NEXT_STATUS: Record<string, string | null> = {
  open: "assigned",
  assigned: "in_progress",
  in_progress: "resolved",
  resolved: "closed",
  closed: "reopened",
  reopened: "in_progress",
};

const MANDATORY_NOTE_TRANSITIONS = new Set(["in_progress->resolved", "resolved->closed", "closed->reopened"]);

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
  const [transitionNote, setTransitionNote] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [assigning, setAssigning] = useState(false);

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
  }

  useEffect(() => {
    load();
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

  const nextStatus = NEXT_STATUS[ticket.status] ?? null;
  const transitionKey = `${ticket.status}->${nextStatus}`;
  const noteRequired = nextStatus !== null && MANDATORY_NOTE_TRANSITIONS.has(transitionKey);

  async function addNote(e: React.FormEvent) {
    e.preventDefault();
    if (!noteText.trim()) return;
    const resp = await fetch(`/api/tickets/${params.id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: noteText }),
    });
    setStatusMsg(resp.ok ? "Note added." : "Failed to add note.");
    if (resp.ok) setNoteText("");
    await load();
  }

  async function sendReply(e: React.FormEvent) {
    e.preventDefault();
    if (!replyText.trim() || !ticket) return;
    const resp = await fetch(`/api/tickets/${params.id}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: replyText }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setStatusMsg(data?.error?.message ?? "Failed to send reply.");
    } else if (ticket.channelOrigin === "email") {
      setStatusMsg(data.emailSent ? "Reply emailed to the citizen." : `Recorded, but not emailed: ${data.emailError ?? "unknown reason"}`);
    } else {
      setStatusMsg(`Reply recorded (no outbound send wired for "${ticket.channelOrigin}" yet).`);
    }
    if (resp.ok) setReplyText("");
    await load();
  }

  async function transition() {
    if (!nextStatus) return;
    if (noteRequired && transitionNote.trim().length < 20) {
      setStatusMsg("This transition requires a note of at least 20 characters.");
      return;
    }
    const resp = await fetch(`/api/tickets/${params.id}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toStatus: nextStatus, note: transitionNote || undefined }),
    });
    const data = await resp.json().catch(() => ({}));
    setStatusMsg(resp.ok ? `Status changed to ${nextStatus}.` : (data?.error?.message ?? "Transition failed."));
    if (resp.ok) setTransitionNote("");
    await load();
  }

  return (
    <main className="mx-auto max-w-6xl bg-slate-50 p-6">
      <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
        ← Back to ticket queue
      </Link>

      <div className="mt-3 mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold text-indigo-700">{ticket.ticketNumber}</h1>
        <span className={statusBadgeClass(ticket.status)}>{ticket.status.replace("_", " ")}</span>
      </div>

      {statusMsg && <p className="mb-4 rounded border bg-white p-2 text-sm shadow-sm">{statusMsg}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
        {/* Left column: the stuff agents act on first. */}
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

          {nextStatus && (
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <h3 className="mb-2 text-sm font-semibold text-slate-700">
                Move to &quot;{nextStatus}&quot;
              </h3>
              {noteRequired && (
                <textarea
                  className="mb-2 w-full rounded border p-2 text-sm"
                  placeholder="Mandatory note (min 20 characters) for this transition"
                  value={transitionNote}
                  onChange={(e) => setTransitionNote(e.target.value)}
                  rows={2}
                />
              )}
              <button onClick={transition} className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
                Transition to {nextStatus}
              </button>
            </div>
          )}

          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Internal notes</h2>
            {ticket.notes.length === 0 ? (
              <p className="text-sm text-muted-foreground">No notes yet.</p>
            ) : (
              <ul className="max-h-64 space-y-2 overflow-y-auto">
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
            <form onSubmit={addNote} className="mt-3 space-y-2">
              <textarea
                className="w-full rounded border p-2 text-sm"
                placeholder="Add an internal note (not sent to the citizen)"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={2}
              />
              <button className="rounded border px-3 py-2 text-sm hover:bg-muted/50">Add note</button>
            </form>
          </section>

          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">Write an update</h2>
            <form onSubmit={sendReply} className="space-y-2">
              <textarea
                className="w-full rounded border p-2 text-sm"
                placeholder={
                  ticket.channelOrigin === "email"
                    ? "Write an update — this will be emailed to the citizen"
                    : "Write an update (outbound send isn't wired for this channel yet)"
                }
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                rows={3}
              />
              <button className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
                Send update
              </button>
            </form>
          </section>
        </div>

        {/* Right column: the reference material, scrolls on its own. */}
        <div className="rounded-lg border bg-white p-4 shadow-sm lg:sticky lg:top-4 lg:self-start">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Conversation</h2>
          {ticket.messages.length === 0 ? (
            <p className="text-sm text-muted-foreground">No messages yet.</p>
          ) : (
            <ul className="max-h-[80vh] space-y-2 overflow-y-auto pr-1">
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
        </div>
      </div>
    </main>
  );
}
