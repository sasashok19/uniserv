"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, RefreshCw } from "lucide-react";

type ServiceHealth = { name: string; port: number; status: "healthy" | "unhealthy" };

/**
 * Administration → System (UI_REVAMP_v2 Feature D): service health dots and the
 * password + typed-RESET gated tenant database reset. The confirm button stays
 * disabled until the password is non-empty AND the confirmation equals RESET
 * exactly; the modal cannot be dismissed by clicking outside it.
 */
export default function SystemPanel() {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [checking, setChecking] = useState(false);
  const [showReset, setShowReset] = useState(false);

  const checkHealth = useCallback(async () => {
    setChecking(true);
    try {
      const resp = await fetch("/api/system/health");
      const data = await resp.json().catch(() => ({}));
      setServices(Array.isArray(data.services) ? data.services : []);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const timer = setInterval(checkHealth, 30_000);
    return () => clearInterval(timer);
  }, [checkHealth]);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700">Service Health</h3>
          <button
            onClick={checkHealth}
            className="flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs hover:bg-muted/50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        <ul className="mt-3 space-y-2">
          {services.length === 0 && <li className="text-sm text-muted-foreground">Checking services…</li>}
          {services.map((s) => (
            <li key={s.name} className="flex items-center gap-3 text-sm">
              <span
                className={`h-2.5 w-2.5 rounded-full ${s.status === "healthy" ? "bg-emerald-500" : "bg-red-500"}`}
              />
              <span className="w-28 font-medium text-slate-700">{s.name}</span>
              <span className="text-muted-foreground">:{s.port}</span>
              <span className={s.status === "healthy" ? "text-emerald-600" : "text-red-600"}>
                {s.status === "healthy" ? "Healthy" : "Unreachable"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border border-[#E07B54]/40 bg-[#FFF0EB]/40 p-4">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-[#E07B54]">
          <AlertTriangle className="h-4 w-4" /> Danger Zone
        </h3>
        <div className="mt-3">
          <p className="font-medium text-slate-800">Reset Database</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Permanently deletes all tickets, identities, notes, messages, and announcements for this tenant.
            Your admin account is preserved. This action cannot be undone.
          </p>
          <button
            onClick={() => setShowReset(true)}
            className="mt-3 rounded border border-[#E07B54] px-4 py-2 text-sm font-medium text-[#E07B54] hover:bg-[#FFF0EB]"
          >
            Reset Database
          </button>
        </div>
      </section>

      {showReset && <ResetModal onClose={() => setShowReset(false)} />}
    </div>
  );
}

function ResetModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const valid = password.length > 0 && confirmation === "RESET";

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      const resp = await fetch("/api/admin/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, confirmation }),
      });
      if (resp.ok) {
        setDone(true);
        setTimeout(() => router.push("/login"), 1500);
        return;
      }
      setSubmitting(false);
      if (resp.status === 401) {
        setError("Incorrect password.");
      } else if (resp.status === 429) {
        setError("Please wait 60 seconds before trying again.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } catch {
      setSubmitting(false);
      setError("Something went wrong. Please try again.");
    }
  }

  return (
    // Overlay click deliberately does NOT close — destructive modal (spec §D).
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md space-y-3 rounded-lg bg-white p-5 shadow-xl">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-red-600">
          <AlertTriangle className="h-4 w-4" /> Reset Database
        </h4>
        {done ? (
          <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">
            Database reset. Redirecting to login…
          </p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              This will permanently delete all data for this tenant. Your admin account will be preserved.
            </p>
            <label className="block text-xs text-muted-foreground">
              Enter your password:
              <input
                type="password"
                className="mt-1 w-full rounded border p-2 text-sm"
                value={password}
                disabled={submitting}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label className="block text-xs text-muted-foreground">
              Type RESET to confirm:
              <input
                className="mt-1 w-full rounded border p-2 text-sm"
                value={confirmation}
                disabled={submitting}
                onChange={(e) => setConfirmation(e.target.value)}
              />
            </label>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                disabled={submitting}
                className="rounded border px-3 py-2 text-sm hover:bg-muted/50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={!valid || submitting}
                className="rounded bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {submitting ? "Resetting…" : "Reset Everything"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
