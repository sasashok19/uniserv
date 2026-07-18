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

type CatalogEntry = { key: string; label: string };
type FieldConfig = { key: string; mandatory: boolean; mandatoryIfAnonymous: boolean };
type CellState = "none" | "optional" | "mandatory" | "anon";

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
  const [config, setConfig] = useState<ConfigMap>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [serverError, setServerError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      const resp = await fetch("/api/tenant/intake-fields");
      const data = await resp.json().catch(() => ({}));
      setCatalog(Array.isArray(data.catalog) ? data.catalog : []);
      setConfig(toConfigMap(data.fields ?? {}));
      setLoading(false);
    })();
  }, []);

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
                <td className="p-2 font-medium text-slate-700">{field.label}</td>
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
