"use client";

import { useEffect, useState } from "react";

/**
 * Administration → Priority Rules (Feature 3): a free-text rubric the AI uses to
 * score ticket priority. When set (and an LLM is available) ai-core applies the
 * rubric; otherwise it falls back to the deterministic engine. The textarea is
 * pre-filled with the stored rubric or, if none is set, today&apos;s default
 * logic so leaving it unchanged keeps the current behavior.
 */
export default function PriorityRulesPanel() {
  const [rubric, setRubric] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [serverError, setServerError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      const resp = await fetch("/api/tenant/priority-rubric");
      const data = await resp.json().catch(() => ({}));
      setRubric(data.rubric || data.default || "");
      setLoading(false);
    })();
  }, []);

  async function save() {
    setSaving(true);
    setMessage("");
    setServerError("");
    const resp = await fetch("/api/tenant/priority-rubric", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rubric }),
    });
    setSaving(false);
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      setRubric(data.rubric || data.default || "");
      setMessage("Priority rubric saved.");
      return;
    }
    const data = await resp.json().catch(() => ({}));
    setServerError(data?.error?.message ?? "Failed to save priority rubric.");
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">Priority Rules</h3>
          <p className="text-xs text-muted-foreground">
            Describe how the assistant should score ticket priority. Leaving the default text keeps
            today&apos;s behavior.
          </p>
        </div>
        <button
          onClick={save}
          disabled={saving}
          className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      {message && <p className="rounded-lg bg-indigo-50 p-2 text-sm text-indigo-700">{message}</p>}
      {serverError && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{serverError}</p>}

      <textarea
        value={rubric}
        onChange={(e) => {
          setMessage("");
          setServerError("");
          setRubric(e.target.value);
        }}
        rows={18}
        className="w-full rounded-lg border bg-white p-3 font-mono text-sm shadow-sm focus:border-indigo-400 focus:outline-none"
      />

      <p className="text-xs text-muted-foreground">
        The rubric is applied only when an AI model is configured; otherwise the built-in
        deterministic engine is used. Clearing the text restores the default logic.
      </p>
    </div>
  );
}
