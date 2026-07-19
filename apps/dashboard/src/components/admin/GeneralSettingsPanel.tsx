"use client";

import { useEffect, useState } from "react";

/**
 * Administration → Settings (Feature 4): general per-tenant settings. Currently
 * just the maximum number of follow-up questions the assistant may ask a citizen
 * during intake (0-5). ai-core reads this per tenant, falling back to its env
 * default when unset.
 */
export default function GeneralSettingsPanel() {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [serverError, setServerError] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      const resp = await fetch("/api/tenant/general-settings");
      const data = await resp.json().catch(() => ({}));
      const current = data?.settings?.maxFollowupQuestions;
      const fallback = data?.defaults?.maxFollowupQuestions;
      const initial = typeof current === "number" ? current : fallback;
      setValue(typeof initial === "number" ? String(initial) : "");
      setLoading(false);
    })();
  }, []);

  async function save() {
    setMessage("");
    setServerError("");
    setValidationError("");
    const parsed = Number(value);
    if (value.trim() === "" || !Number.isInteger(parsed) || parsed < 0 || parsed > 5) {
      setValidationError("Enter a whole number between 0 and 5.");
      return;
    }
    setSaving(true);
    const resp = await fetch("/api/tenant/general-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maxFollowupQuestions: parsed }),
    });
    setSaving(false);
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const current = data?.settings?.maxFollowupQuestions;
      if (typeof current === "number") setValue(String(current));
      setMessage("Settings saved.");
      return;
    }
    const data = await resp.json().catch(() => ({}));
    setServerError(data?.error?.message ?? "Failed to save settings.");
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">Settings</h3>
          <p className="text-xs text-muted-foreground">
            General assistant behavior for your tenant.
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
      {validationError && (
        <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{validationError}</p>
      )}

      <div className="max-w-sm rounded-lg border bg-white p-4 shadow-sm">
        <label htmlFor="maxFollowupQuestions" className="block text-sm font-medium text-slate-700">
          Max follow-up questions
        </label>
        <p className="mb-2 text-xs text-muted-foreground">
          How many clarifying questions the assistant may ask during intake (0-5).
        </p>
        <input
          id="maxFollowupQuestions"
          type="number"
          min={0}
          max={5}
          step={1}
          value={value}
          onChange={(e) => {
            setMessage("");
            setServerError("");
            setValidationError("");
            setValue(e.target.value);
          }}
          className="w-24 rounded border p-2 text-sm"
        />
      </div>
    </div>
  );
}
