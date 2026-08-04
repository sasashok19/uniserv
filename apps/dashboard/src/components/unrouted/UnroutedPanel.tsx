"use client";

import { useCallback, useEffect, useState } from "react";
import { Inbox, Loader2 } from "lucide-react";

type UnroutedMessage = {
  id: string;
  channel: string;
  channel_identity_value: string | null;
  content: string;
  reason: string | null;
  status: string;
  ask_count: number;
  created_at: string | null;
};

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-900",
  escalated: "bg-red-100 text-red-900",
};

/**
 * The unrouted-message queue (Feature 24) — lead/admin only.
 *
 * These are messages routing could not attribute to any ticket and deliberately
 * did not invent one for: a bare "yes"/"ok"/"you are correct" that answers
 * nothing we asked and describes no problem. Before this existed such a message
 * either created a junk ticket or was appended to an unrelated one (which is
 * exactly the bug Feature 24 fixes), and dropping it would have been worse
 * still: nobody can fix what was never stored.
 *
 * Two outcomes per row: **Attach** it to the ticket it belonged to (which also
 * copies it onto that ticket's conversation — clearing the queue without
 * delivering the message would defeat the point), or **Discard** it as noise.
 * A `pending` row means the citizen has been asked for a ticket reference;
 * `escalated` means they were asked already and the next message was also
 * unroutable, so a human needs to step in rather than the bot asking again.
 */
export default function UnroutedPanel() {
  const [messages, setMessages] = useState<UnroutedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [ticketRefs, setTicketRefs] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/unrouted-messages");
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setError(data?.error?.message ?? "Could not load unrouted messages.");
        setMessages([]);
        return;
      }
      setMessages(Array.isArray(data.messages) ? data.messages : []);
      setTotal(typeof data.total === "number" ? data.total : 0);
    } catch {
      setError("Could not load unrouted messages.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function attach(id: string) {
    const ticketNumber = (ticketRefs[id] ?? "").trim();
    if (!ticketNumber) {
      setStatusMsg("Enter the ticket number this message belongs to (e.g. TKT-00010).");
      return;
    }
    setBusyId(id);
    const resp = await fetch(`/api/unrouted-messages/${id}/attach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticketNumber }),
    });
    const data = await resp.json().catch(() => ({}));
    setBusyId(null);
    setStatusMsg(
      resp.ok
        ? `Filed against ${ticketNumber} and added to its conversation.`
        : data?.error?.message ?? "Could not attach this message.",
    );
    if (resp.ok) await load();
  }

  async function discard(id: string) {
    if (!window.confirm("Discard this message as noise? It stays on record but leaves this queue.")) {
      return;
    }
    setBusyId(id);
    const resp = await fetch(`/api/unrouted-messages/${id}/discard`, { method: "POST" });
    const data = await resp.json().catch(() => ({}));
    setBusyId(null);
    setStatusMsg(resp.ok ? "Discarded." : data?.error?.message ?? "Could not discard this message.");
    if (resp.ok) await load();
  }

  if (loading) {
    return <p className="rounded-lg border bg-white p-4 text-sm text-slate-500 shadow-sm">Loading…</p>;
  }
  if (error) {
    return <p className="rounded-lg border bg-white p-4 text-sm text-red-700 shadow-sm">{error}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-white p-4 shadow-sm">
        <h2 className="text-base font-semibold text-slate-800">
          Unrouted messages{" "}
          <span className="text-sm font-normal text-slate-500">
            ({total} awaiting a decision)
          </span>
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Citizen messages we could not attribute to a ticket — typically a bare
          &ldquo;yes&rdquo; or &ldquo;ok&rdquo; that answers nothing we asked and describes no problem.
          No ticket was created for them; the citizen has been asked which complaint they mean.
          <strong className="font-semibold"> Escalated</strong> means they were asked once already.
        </p>
        {statusMsg && <p className="mt-2 rounded border bg-slate-50 p-2 text-sm">{statusMsg}</p>}
      </div>

      {messages.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border bg-white p-4 text-sm text-slate-600 shadow-sm">
          <Inbox className="h-4 w-4 text-slate-400" aria-hidden />
          Nothing unrouted — every recent message reached a ticket.
        </p>
      ) : (
        <ul className="space-y-3">
          {messages.map((m) => (
            <li key={m.id} className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span
                  className={`rounded-full px-2 py-0.5 font-medium ${
                    STATUS_STYLE[m.status] ?? "bg-slate-100 text-slate-700"
                  }`}
                >
                  {m.status}
                </span>
                <span className="capitalize">{m.channel}</span>
                <span>{m.channel_identity_value ?? "unknown sender"}</span>
                <span>{m.created_at ?? ""}</span>
              </div>

              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-800">{m.content}</p>
              {m.reason && (
                <p className="mt-1 text-xs italic text-slate-500">Why it wasn&apos;t routed: {m.reason}</p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <label className="text-xs text-slate-600" htmlFor={`ref-${m.id}`}>
                  Belongs to
                </label>
                <input
                  id={`ref-${m.id}`}
                  value={ticketRefs[m.id] ?? ""}
                  onChange={(e) => setTicketRefs((r) => ({ ...r, [m.id]: e.target.value }))}
                  placeholder="TKT-00010"
                  className="w-36 rounded border p-1.5 text-sm placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                />
                <button
                  onClick={() => attach(m.id)}
                  disabled={busyId === m.id}
                  className="inline-flex items-center gap-1.5 rounded bg-brand-teal px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 active:scale-[0.97] disabled:opacity-50"
                >
                  {busyId === m.id && <Loader2 className="h-4 w-4 animate-spin" />}
                  Attach
                </button>
                <button
                  onClick={() => discard(m.id)}
                  disabled={busyId === m.id}
                  className="rounded border px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 active:scale-[0.97] disabled:opacity-50"
                >
                  Discard
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
