"use client";

import { useEffect, useState } from "react";

/**
 * Administration → WhatsApp Menu (Feature 26).
 *
 * Every string a citizen reads on WhatsApp, including the company name the
 * welcome greets them with. Stored under `config_json.whatsappMenu`; the
 * gateway (`WhatsAppMenuContent.java`) owns the defaults and validation, and
 * ai-core reads the same blob to compose the live messages.
 *
 * Two conventions carried over from the landing-page panel, both load-bearing:
 * **blank means "use the default"** (never a blank message to a citizen), and
 * the server's RESOLVED view is what gets shown back after a save, so a field
 * the admin cleared visibly fills back in with its default.
 */

type Field = {
  key: string;
  label: string;
  help: string;
  rows?: number;
  placeholders?: string[];
};

/** Grouped the way the conversation actually runs, so an admin can read the
 * panel top to bottom and follow what the citizen will see. */
const GROUPS: { title: string; blurb: string; fields: Field[] }[] = [
  {
    title: "Welcome & menu",
    blurb: "The first thing the citizen receives, and what they see whenever they press #.",
    fields: [
      {
        key: "companyName",
        label: "Company name",
        help: "Used wherever {company} appears. Leave blank to use the landing page's brand name.",
      },
      {
        key: "welcome",
        label: "Welcome message",
        help: "Sent when a conversation starts from a number we don't recognise.",
        placeholders: ["{company}"],
      },
      {
        key: "welcomeNamed",
        label: "Welcome message (known number)",
        help: "Used when the number is already in the system. Must include {name}.",
        placeholders: ["{name}", "{company}"],
      },
      {
        key: "menuIntro",
        label: "Prompt above the options",
        help: "Shown with the tappable options. Only used when they are on.",
      },
      {
        key: "labelProfile",
        label: "Option 1 — update my details",
        help: "Max 20 characters (WhatsApp's limit).",
      },
      {
        key: "labelStatus",
        label: "Option 2 — existing ticket",
        help: "Max 20 characters.",
      },
      {
        key: "labelNewTicket",
        label: "Option 3 — new ticket",
        help: "Max 20 characters.",
      },
      {
        key: "labelEndChat",
        label: "Option 4 — end chat",
        help: "Max 20 characters.",
      },
      {
        key: "labelMainMenu",
        label: "Back to the main menu",
        help: "On every message below the top level. Max 20 characters.",
      },
      {
        key: "listButtonLabel",
        label: "Label that opens the list",
        help: "Four options can't be buttons — WhatsApp caps those at three — so they arrive as a list behind this label. Max 20 characters.",
      },
      {
        key: "menuPrompt",
        label: "Menu options (text fallback)",
        help: "Used when the tappable options are switched off, and if WhatsApp rejects an interactive send. Must still offer 1, 2, 3 and 4.",
        rows: 5,
      },
      {
        key: "menuHint",
        label: "Return-to-menu hint",
        help: "Appended to every message except the goodbye. Leave blank only if you mean to remove it.",
      },
      {
        key: "unknownOption",
        label: "Unrecognised input",
        help: "Shown with the menu when the citizen types something instead of choosing — but only at the main menu, never mid-flow.",
      },
    ],
  },
  {
    title: "Option 1 — update my details",
    blurb:
      "The citizen correcting their own name or email. WhatsApp has no form outside a published Flow, so we ask and their reply is the answer.",
    fields: [
      { key: "profilePrompt", label: "Name or email?", help: "" },
      { key: "labelNameOption", label: "Button — name", help: "Max 20 characters." },
      { key: "labelEmailOption", label: "Button — email", help: "Max 20 characters." },
      { key: "askName", label: "Ask for the name", help: "" },
      {
        key: "profileUnknownName",
        label: "Ask for the name (first time)",
        help: "Used when we hold no name for this number, so the ask needs explaining.",
        rows: 2,
      },
      { key: "askEmail", label: "Ask for the email", help: "" },
      { key: "nameUpdated", label: "Name saved", help: "", placeholders: ["{name}"] },
      { key: "emailUpdated", label: "Email saved", help: "", placeholders: ["{email}"] },
      { key: "nameInvalid", label: "That isn't a name", help: "", rows: 2 },
      { key: "emailInvalid", label: "That isn't an email address", help: "", rows: 2 },
      {
        key: "emailInUse",
        label: "Email belongs to someone else",
        help: "Refused rather than moved: taking an address that identifies another person would reassign their tickets.",
        rows: 3,
      },
    ],
  },
  {
    title: "Option 2 — existing ticket",
    blurb: "Their open and resolved tickets, tappable — or a request for the number when there are more than five.",
    fields: [
      { key: "ticketListIntro", label: "Above the list", help: "" },
      { key: "ticketListEmpty", label: "No tickets to show", help: "", rows: 2 },
      {
        key: "ticketListMany",
        label: "Too many to list",
        help: "Shown above the ten most recent when they have more than five.",
        rows: 3,
        placeholders: ["{count}"],
      },
      {
        key: "ticketRowTitle",
        label: "List row — title",
        help: "Clipped to 24 characters by WhatsApp. Must include {ticket}.",
        placeholders: ["{ticket}", "{complaint}"],
      },
      {
        key: "ticketRowDescription",
        label: "List row — second line",
        help: "Clipped to 72 characters. This is where the detail fits.",
        placeholders: ["{status}", "{eta}", "{updated}", "{complaint}"],
      },
      {
        key: "labelTypeTicketId",
        label: "Row — none of these",
        help: "Max 20 characters.",
      },
      { key: "askTicketId", label: "Ask for the Ticket ID", help: "" },
      {
        key: "ticketNotFound",
        label: "Ticket not found",
        help: "Also shown when the ticket belongs to someone else — deliberately identical, so the reply can't be used to discover other people's tickets.",
        rows: 3,
      },
      {
        key: "ticketDetails",
        label: "Ticket details",
        help: "Must include {ticket}.",
        rows: 4,
        placeholders: ["{ticket}", "{complaint}", "{status}", "{eta}", "{updated}"],
      },
      { key: "etaUnknown", label: "ETA not set yet", help: "Substituted for {eta} when no ETA has been set." },
      {
        key: "complaintUnknown",
        label: "Complaint not summarised yet",
        help: "Substituted for {complaint} on a ticket with no chief complaint yet.",
      },
      { key: "inviteNote", label: "Invite a note", help: "", rows: 3 },
      {
        key: "noteAdded",
        label: "Note added",
        help: "",
        rows: 2,
        placeholders: ["{ticket}"],
      },
    ],
  },
  {
    title: "Option 3 — new ticket",
    blurb: "The details needed are appended automatically from your Intake Fields configuration.",
    fields: [
      { key: "registerIntro", label: "Start registration", help: "", rows: 2 },
      {
        key: "askComplaint",
        label: "Ask for the complaint",
        help: "Used instead of the above when no intake fields are configured, so the citizen is never asked to 'reply with the following details' and then shown nothing.",
        rows: 3,
      },
      {
        key: "ticketCreated",
        label: "Ticket registered",
        help: "The single message that closes out a registration. Must include {ticket}.",
        rows: 4,
        placeholders: ["{ticket}", "{complaint}", "{status}", "{eta}", "{updated}"],
      },
    ],
  },
  {
    title: "Duplicates",
    blurb:
      "When a new complaint might repeat an open one, the citizen is asked before any ticket is created.",
    fields: [
      {
        key: "duplicateAsk",
        label: "Ask about a possible duplicate",
        help: "{question} is written by the AI and asks for the missing detail (usually the area).",
        rows: 3,
        placeholders: ["{ticket}", "{existing}", "{question}"],
      },
      {
        key: "duplicateMerged",
        label: "Added to the existing ticket",
        help: "",
        rows: 3,
        placeholders: ["{ticket}", "{complaint}", "{status}", "{eta}"],
      },
    ],
  },
  {
    title: "Ending the chat",
    blurb: "",
    fields: [
      { key: "conversationEnd", label: "Conversation ended", help: "", rows: 3 },
      {
        key: "farewell",
        label: "Goodbye (end chat)",
        help: "The one message with no way back on it — offering a menu we have just closed contradicts the goodbye.",
        rows: 2,
      },
    ],
  },
];

const ALL_KEYS = GROUPS.flatMap((g) => g.fields.map((f) => f.key));

export default function WhatsAppMenuPanel() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [enabled, setEnabled] = useState(true);
  const [useButtons, setUseButtons] = useState(true);
  const [ttl, setTtl] = useState("12");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function clearMessages() {
    setMessage("");
    setError("");
  }

  function apply(content: Record<string, unknown>) {
    const next: Record<string, string> = {};
    for (const key of ALL_KEYS) {
      next[key] = typeof content[key] === "string" ? (content[key] as string) : "";
    }
    setValues(next);
    setEnabled(content.enabled !== false);
    setUseButtons(content.useInteractiveButtons !== false);
    setTtl(typeof content.sessionTtlHours === "number" ? String(content.sessionTtlHours) : "12");
  }

  useEffect(() => {
    (async () => {
      setLoading(true);
      const resp = await fetch("/api/tenant/whatsapp-menu");
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data?.content) apply(data.content);
      else setError(data?.error?.message ?? "Could not load the WhatsApp menu.");
      setLoading(false);
    })();
  }, []);

  async function save() {
    clearMessages();
    setSaving(true);
    const resp = await fetch("/api/tenant/whatsapp-menu", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...values,
        enabled,
        useInteractiveButtons: useButtons,
        sessionTtlHours: Number(ttl) || undefined,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    setSaving(false);
    if (resp.ok && data?.content) {
      // Echo the RESOLVED view so a field left blank visibly fills back in
      // with its default rather than looking as though it saved as empty.
      apply(data.content);
      setMessage("WhatsApp menu saved.");
      return;
    }
    setError(data?.error?.message ?? "Failed to save the WhatsApp menu.");
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-slate-800">WhatsApp Menu</h3>
          <p className="text-xs text-slate-600">
            Everything a citizen reads on WhatsApp. Leave a field blank to use its default.
          </p>
        </div>
        <button
          onClick={save}
          disabled={saving}
          className="shrink-0 rounded bg-brand-teal px-3 py-2 text-sm font-medium text-white transition-transform hover:bg-brand-tealDark active:scale-[0.97] disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      {message && <p className="rounded-lg bg-brand-tealTint p-2 text-sm text-brand-tealDark">{message}</p>}
      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      <div className="rounded-lg border bg-white p-4 shadow-sm">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              clearMessages();
              setEnabled(e.target.checked);
            }}
          />
          Menu enabled
        </label>
        <p className="mt-1 text-xs text-slate-600">
          When off, WhatsApp messages go straight to the AI assistant with no welcome and no
          numbered options — the behaviour before this feature.
        </p>

        <label className="mt-4 flex items-center gap-2 text-sm font-medium text-slate-700">
          <input
            type="checkbox"
            checked={useButtons}
            onChange={(e) => {
              clearMessages();
              setUseButtons(e.target.checked);
            }}
          />
          Show the options as tappable buttons
        </label>
        <p className="mt-1 text-xs text-slate-600">
          Sends the menu as a WhatsApp interactive message — three buttons instead of
          &quot;press 1&quot;. Switch off to send the numbered text above instead. WhatsApp allows
          at most 3 buttons and 20 characters per label, which is why the options are fixed at three.
        </p>

        <label htmlFor="sessionTtlHours" className="mt-4 block text-sm font-medium text-slate-700">
          Session length (hours)
        </label>
        <p className="mb-2 text-xs text-slate-600">
          How long a conversation stays open before the next message re-opens the welcome menu.
          Maximum 24 — WhatsApp only lets us reply freely within 24 hours of the citizen&apos;s last
          message, so a longer session could never be answered.
        </p>
        <input
          id="sessionTtlHours"
          type="number"
          min={1}
          max={24}
          step={1}
          value={ttl}
          onChange={(e) => {
            clearMessages();
            setTtl(e.target.value);
          }}
          className="w-24 rounded border p-2 text-sm"
        />
      </div>

      {GROUPS.map((group) => (
        <div key={group.title} className="rounded-lg border bg-white p-4 shadow-sm">
          <h4 className="text-sm font-semibold text-slate-800">{group.title}</h4>
          {group.blurb && <p className="mt-0.5 text-xs text-slate-600">{group.blurb}</p>}
          <div className="mt-3 space-y-4">
            {group.fields.map((field) => (
              <div key={field.key}>
                <label htmlFor={field.key} className="block text-sm font-medium text-slate-700">
                  {field.label}
                </label>
                {(field.help || field.placeholders) && (
                  <p className="mb-1 text-xs text-slate-600">
                    {field.help}
                    {field.placeholders && (
                      <>
                        {field.help ? " " : ""}
                        Placeholders:{" "}
                        {field.placeholders.map((p, i) => (
                          <span key={p}>
                            {i > 0 && ", "}
                            <code className="rounded bg-slate-100 px-1">{p}</code>
                          </span>
                        ))}
                      </>
                    )}
                  </p>
                )}
                {field.rows && field.rows > 1 ? (
                  <textarea
                    id={field.key}
                    rows={field.rows}
                    value={values[field.key] ?? ""}
                    onChange={(e) => {
                      clearMessages();
                      setValues({ ...values, [field.key]: e.target.value });
                    }}
                    className="w-full rounded border p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                  />
                ) : (
                  <input
                    id={field.key}
                    type="text"
                    value={values[field.key] ?? ""}
                    onChange={(e) => {
                      clearMessages();
                      setValues({ ...values, [field.key]: e.target.value });
                    }}
                    className="w-full rounded border p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
