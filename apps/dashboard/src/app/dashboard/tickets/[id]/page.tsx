"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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
  priorityLabel: string | null;
  assignedTo: string | null;
  notes: Note[];
  messages: Message[];
};

const NEXT_STATUS: Record<string, string | null> = {
  open: "assigned",
  assigned: "in_progress",
  in_progress: "resolved",
  resolved: "closed",
  closed: "reopened",
  reopened: "in_progress",
};

const MANDATORY_NOTE_TRANSITIONS = new Set(["in_progress->resolved", "resolved->closed", "closed->reopened"]);

export default function TicketDetailPage({ params }: { params: { id: string } }) {
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");
  const [replyText, setReplyText] = useState("");
  const [transitionNote, setTransitionNote] = useState("");
  const [statusMsg, setStatusMsg] = useState("");

  async function load() {
    setLoading(true);
    const resp = await fetch(`/api/tickets/${params.id}`);
    const data = await resp.json();
    setTicket(resp.ok ? data : null);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, [params.id]);

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
    <main className="mx-auto max-w-3xl p-6">
      <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
        ← Back to ticket queue
      </Link>

      <div className="mt-3 mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">{ticket.ticketNumber}</h1>
        <span className="rounded-full border px-3 py-1 text-xs uppercase">{ticket.status}</span>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><span className="text-muted-foreground">Category</span><div>{ticket.category ?? "—"}</div></div>
        <div><span className="text-muted-foreground">Priority</span><div>{ticket.priorityLabel ?? "—"}</div></div>
        <div><span className="text-muted-foreground">Channel</span><div>{ticket.channelOrigin}</div></div>
        <div><span className="text-muted-foreground">Assigned to</span><div>{ticket.assignedTo ?? "Unassigned"}</div></div>
      </div>

      {statusMsg && <p className="mb-4 rounded border bg-muted/30 p-2 text-sm">{statusMsg}</p>}

      {nextStatus && (
        <div className="mb-6 rounded-lg border p-4">
          <h3 className="mb-2 text-sm font-semibold">Move to &quot;{nextStatus}&quot;</h3>
          {noteRequired && (
            <textarea
              className="mb-2 w-full rounded border p-2 text-sm"
              placeholder="Mandatory note (min 20 characters) for this transition"
              value={transitionNote}
              onChange={(e) => setTransitionNote(e.target.value)}
              rows={2}
            />
          )}
          <button onClick={transition} className="rounded bg-black px-3 py-2 text-sm text-white">
            Transition to {nextStatus}
          </button>
        </div>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">Conversation</h2>
        {ticket.messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">No messages yet.</p>
        ) : (
          <ul className="space-y-2">
            {ticket.messages.map((m, i) => (
              <li key={i} className={`rounded-lg border p-3 text-sm ${m.direction === "outbound" ? "bg-muted/30" : ""}`}>
                <div className="mb-1 text-xs text-muted-foreground">
                  {m.direction === "outbound" ? "Sent" : "Received"} · {m.authorType} · {m.createdAt}
                </div>
                {m.content}
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={sendReply} className="mt-3 space-y-2">
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
          <button className="rounded bg-black px-3 py-2 text-sm text-white">Send update</button>
        </form>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Internal notes</h2>
        {ticket.notes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No notes yet.</p>
        ) : (
          <ul className="space-y-2">
            {ticket.notes.map((n, i) => (
              <li key={i} className="rounded-lg border p-3 text-sm">
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
          <button className="rounded border px-3 py-2 text-sm">Add note</button>
        </form>
      </section>
    </main>
  );
}
