"use client";

import { useEffect, useState } from "react";

/**
 * Administration → Intake Fields (Feature 16): per-channel configuration of
 * which identity/intake fields the bot asks for and whether each is mandatory.
 *
 * Rows = the field catalog (from the backend, kept in sync with ai-core's
 * Python FIELD_CATALOG). Columns = channels. Each cell picks one of four
 * states that map directly to the backend's {key, mandatory,
 * mandatoryIfAnonymous} shape (absence == "Not asked").
 *
 * A field that's native to a channel (email address on the Email channel,
 * mobile number on the WhatsApp channel) is greyed out — asking for it there
 * is nonsensical since the channel already carries it.
 */

type CatalogEntry = { key: string; label: string; builtin?: boolean };
type CustomField = { key: string; label: string; validation: "text" | "digits"; digits?: number };
type FieldConfig = { key: string; mandatory: boolean; mandatoryIfAnonymous: boolean };
type CellState = "none" | "optional" | "mandatory" | "anon";

/** "Consumer Number" -> "consumerNumber" (letters/digits, letter first, ≤30). */
function deriveKey(label: string): string {
  const words = label.replace(/[^A-Za-z0-9 ]+/g, " ").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  const key = words
    .map((w, i) => (i === 0 ? w.charAt(0).toLowerCase() + w.slice(1) : w.charAt(0).toUpperCase() + w.slice(1)))
    .join("");
  const clean = key.replace(/^[^A-Za-z]+/, "").slice(0, 30);
  return clean;
}

const CHANNELS: { key: string; label: string; native: string }[] = [
  { key: "email", label: "Email", native: "email" },
  { key: "whatsapp", label: "WhatsApp", native: "mobile" },
];

const STATES: { value: CellState; label: string }[] = [
  { value: "none", label: "Not asked" },
  { value: "optional", label: "Optional" },
  { value: "mandatory", label: "Mandatory" },
  { value: "anon", label: "Mandatory even if anonymous" },
];

type ConfigMap = Record<string, Record<string, CellState>>; // channel -> fieldKey -> state

function configToState(field: FieldConfig | undefined): CellState {
  if (!field) return "none";
  if (field.mandatory) return "mandatory";
  if (field.mandatoryIfAnonymous) return "anon";
  return "optional";
}

function stateToConfig(key: string, state: CellState): FieldConfig | null {
  switch (state) {
    case "none":
      return null;
    case "optional":
      return { key, mandatory: false, mandatoryIfAnonymous: false };
    case "mandatory":
      return { key, mandatory: true, mandatoryIfAnonymous: false };
    case "anon":
      return { key, mandatory: false, mandatoryIfAnonymous: true };
  }
}

/** Build the ConfigMap from the backend's {channel: [FieldConfig]} shape. */
function toConfigMap(fields: Record<string, FieldConfig[]>): ConfigMap {
  const map: ConfigMap = {};
  for (const { key: channel } of CHANNELS) {
    const list = Array.isArray(fields[channel]) ? fields[channel] : [];
    const byKey: Record<string, CellState> = {};
    for (const f of list) byKey[f.key] = configToState(f);
    map[channel] = byKey;
  }
  return map;
}

/** Serialise the ConfigMap back to the backend's {channel: [FieldConfig]} shape. */
function toPayload(config: ConfigMap, catalog: CatalogEntry[]): Record<string, FieldConfig[]> {
  const payload: Record<string, FieldConfig[]> = {};
  for (const { key: channel, native } of CHANNELS) {
    const list: FieldConfig[] = [];
    for (const { key } of catalog) {
      if (key === native) continue; // native field never asked on its own channel
      const cfg = stateToConfig(key, config[channel]?.[key] ?? "none");
      if (cfg) list.push(cfg);
    }
    payload[channel] = list;
  }
  return payload;
}

export default function IntakeFieldsPanel() {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [config, setConfig] = useState<ConfigMap>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [serverError, setServerError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newValidation, setNewValidation] = useState<"text" | "digits">("text");
  const [newDigits, setNewDigits] = useState("");

  function applyResponse(data: {
    catalog?: CatalogEntry[];
    customFields?: CustomField[];
    fields?: Record<string, FieldConfig[]>;
  }) {
    setCatalog(Array.isArray(data.catalog) ? data.catalog : []);
    setCustomFields(Array.isArray(data.customFields) ? data.customFields : []);
    if (data.fields) setConfig(toConfigMap(data.fields));
  }

  useEffect(() => {
    (async () => {
      setLoading(true);
      const resp = await fetch("/api/tenant/intake-fields");
      const data = await resp.json().catch(() => ({}));
      applyResponse(data);
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Replace the custom-field catalog (add or remove) via PUT /catalog. */
  async function saveCatalog(next: CustomField[]) {
    setMessage("");
    setServerError("");
    const resp = await fetch("/api/tenant/intake-fields/catalog", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customFields: next }),
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok) {
      applyResponse(data);
      setMessage("Field catalog updated.");
      setShowAdd(false);
      setNewLabel("");
      setNewValidation("text");
      setNewDigits("");
      return;
    }
    setServerError(data?.error?.message ?? "Failed to update field catalog.");
  }

  function addField() {
    const label = newLabel.trim();
    const key = deriveKey(label);
    if (label.length < 2 || !key) {
      setServerError("Enter a field label of at least 2 characters.");
      return;
    }
    const entry: CustomField = { key, label, validation: newValidation };
    if (newValidation === "digits" && newDigits.trim()) {
      const n = Number(newDigits);
      if (!Number.isInteger(n) || n < 1 || n > 20) {
        setServerError("Digits length must be a whole number between 1 and 20.");
        return;
      }
      entry.digits = n;
    }
    saveCatalog([...customFields, entry]);
  }

  function removeField(key: string) {
    if (!window.confirm("Remove this field? It will also be removed from every channel's configuration.")) return;
    saveCatalog(customFields.filter((f) => f.key !== key));
  }

  function setCell(channel: string, fieldKey: string, state: CellState) {
    setMessage("");
    setServerError("");
    setConfig((prev) => ({
      ...prev,
      [channel]: { ...prev[channel], [fieldKey]: state },
    }));
  }

  async function save() {
    setSaving(true);
    setMessage("");
    setServerError("");
    const resp = await fetch("/api/tenant/intake-fields", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toPayload(config, catalog)),
    });
    setSaving(false);
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      if (data.fields) setConfig(toConfigMap(data.fields));
      setMessage("Intake field configuration saved.");
      return;
    }
    const data = await resp.json().catch(() => ({}));
    setServerError(data?.error?.message ?? "Failed to save intake field configuration.");
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">Intake Fields</h3>
          <p className="text-xs text-muted-foreground">
            Choose which details the assistant collects on each channel and whether each is required.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="rounded border border-indigo-600 px-3 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50"
          >
            {showAdd ? "Cancel" : "Add field"}
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>

      {message && <p className="rounded-lg bg-indigo-50 p-2 text-sm text-indigo-700">{message}</p>}
      {serverError && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{serverError}</p>}

      {showAdd && (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-4">
          <label className="text-xs text-muted-foreground">
            Field label
            <input
              className="mt-1 block w-56 rounded border p-2 text-sm"
              placeholder="e.g. Consumer Number"
              maxLength={40}
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
            />
          </label>
          <label className="text-xs text-muted-foreground">
            Validation
            <select
              className="mt-1 block rounded border p-2 text-sm"
              value={newValidation}
              onChange={(e) => setNewValidation(e.target.value as "text" | "digits")}
            >
              <option value="text">Free text</option>
              <option value="digits">Numeric</option>
            </select>
          </label>
          {newValidation === "digits" && (
            <label className="text-xs text-muted-foreground">
              Exact digits (optional)
              <input
                type="number"
                min={1}
                max={20}
                className="mt-1 block w-24 rounded border p-2 text-sm"
                value={newDigits}
                onChange={(e) => setNewDigits(e.target.value)}
              />
            </label>
          )}
          <button
            onClick={addField}
            className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Add
          </button>
          <p className="w-full text-xs text-muted-foreground">
            New fields cascade automatically: the assistant asks for them per this grid, extracts and
            validates replies, and shows the values on the ticket.
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-muted-foreground">
            <tr>
              <th className="p-2">Field</th>
              {CHANNELS.map((c) => (
                <th key={c.key} className="p-2">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {catalog.map((field) => (
              <tr key={field.key} className="border-t">
                <td className="p-2 font-medium text-slate-700">
                  <span className="flex items-center gap-2">
                    {field.label}
                    {field.builtin === false && (
                      <button
                        onClick={() => removeField(field.key)}
                        title="Remove this custom field"
                        className="rounded px-1 text-xs text-red-500 hover:bg-red-50"
                      >
                        ✕
                      </button>
                    )}
                  </span>
                </td>
                {CHANNELS.map((channel) => {
                  const isNative = channel.native === field.key;
                  return (
                    <td key={channel.key} className="p-2">
                      {isNative ? (
                        <span className="text-xs italic text-muted-foreground">
                          Provided by channel
                        </span>
                      ) : (
                        <select
                          className="w-full rounded border p-2 text-sm"
                          value={config[channel.key]?.[field.key] ?? "none"}
                          onChange={(e) => setCell(channel.key, field.key, e.target.value as CellState)}
                        >
                          {STATES.map((s) => (
                            <option key={s.value} value={s.value}>{s.label}</option>
                          ))}
                        </select>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        Each channel needs at least one mandatory identity field (Name, Mobile, or Email) so every
        ticket can be tied to a citizen. &ldquo;Mandatory even if anonymous&rdquo; is still required
        when the citizen declines to share their name.
      </p>
    </div>
  );
}
