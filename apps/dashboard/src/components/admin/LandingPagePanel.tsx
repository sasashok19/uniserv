"use client";

import { useEffect, useState } from "react";

import {
  DEFAULT_LANDING_PAGE,
  coerceLandingPage,
  type LandingPageContent,
  type LandingSection,
} from "@/lib/landingPage";

/**
 * Administration → Landing Page (Feature 25): everything a citizen reads on the
 * public `/` page, so re-deploying UniServe for another tenant is an edit here
 * rather than a change to `src/app/page.tsx`.
 *
 * Two rules the fields below rely on:
 * - **Blank means "use the default".** Clearing a box does not blank the public
 *   page; the gateway's `LandingPageContent.resolve` fills it back in. The
 *   placeholders show what each blank field will fall back to.
 * - **The whole object is sent on save.** The gateway replaces its `landingPage`
 *   key wholesale (while preserving the rest of `config_json`), so a partial
 *   submit would silently drop fields — hence one form, one Save.
 */

const COLOR_FIELDS: { key: keyof LandingPageContent["colors"]; label: string; help: string }[] = [
  { key: "from", label: "Gradient start", help: "Top-left of the hero, and the footer background" },
  { key: "via", label: "Gradient middle", help: "Mid-point of the hero wash" },
  { key: "to", label: "Gradient end", help: "Bottom-right of the hero" },
  { key: "accent", label: "Button start", help: "Left stop of the track-complaint button" },
  { key: "accentTo", label: "Button end", help: "Right stop of the track-complaint button" },
];

const CONTACT_FIELDS: { key: "email" | "phone" | "whatsapp" | "address" | "hours"; label: string }[] = [
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "address", label: "Address" },
  { key: "hours", label: "Hours" },
];

export default function LandingPagePanel() {
  const [content, setContent] = useState<LandingPageContent>(DEFAULT_LANDING_PAGE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const resp = await fetch("/api/tenant/landing-page");
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
          setContent(coerceLandingPage(data?.content));
        } else {
          setError(data?.error?.message ?? "Failed to load landing page content.");
        }
      } catch {
        setError("Failed to load landing page content.");
      }
      setLoading(false);
    })();
  }, []);

  function set<K extends keyof LandingPageContent>(key: K, value: LandingPageContent[K]) {
    setMessage("");
    setError("");
    setContent((c) => ({ ...c, [key]: value }));
  }

  async function save() {
    setMessage("");
    setError("");
    setSaving(true);
    try {
      const resp = await fetch("/api/tenant/landing-page", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(content),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        // Repaint from the RESOLVED response so any field left blank visibly
        // becomes the default it fell back to, rather than staying empty.
        setContent(coerceLandingPage(data?.content));
        setMessage("Saved. The public page picks this up within a minute.");
      } else {
        setError(data?.error?.message ?? "Failed to save landing page content.");
      }
    } catch {
      setError("Failed to save landing page content.");
    }
    setSaving(false);
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-slate-800">Landing Page</h3>
          <p className="text-xs text-slate-600">
            What citizens see on the public home page. Leave a box blank to use the default shown
            in grey.{" "}
            <a href="/" target="_blank" rel="noreferrer" className="text-brand-teal underline">
              Open the page
            </a>
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

      {/* ---- Brand -------------------------------------------------- */}
      <Group title="Brand" help="Shown in the header and as the big hero headline.">
        <Field
          label="Brand name"
          value={content.brandName}
          placeholder={DEFAULT_LANDING_PAGE.brandName}
          onChange={(v) => set("brandName", v)}
        />
        <Field
          label="Logo URL"
          value={content.logoUrl}
          placeholder="/tenants/acme/logo.png or https://acme.example/logo.svg"
          help="A path to an image committed under apps/dashboard/public (e.g. /tenants/acme/logo.png), or an absolute https URL. Blank shows the brand name as text instead."
          onChange={(v) => set("logoUrl", v)}
        />
        <Field
          label="Tagline"
          value={content.tagline}
          placeholder={DEFAULT_LANDING_PAGE.tagline}
          onChange={(v) => set("tagline", v)}
        />
        <Field
          label="Sub-tagline"
          value={content.subTagline}
          placeholder={DEFAULT_LANDING_PAGE.subTagline}
          onChange={(v) => set("subTagline", v)}
        />
      </Group>

      {/* ---- Colours ------------------------------------------------ */}
      <Group title="Colours" help="Hex values such as #0D1B2A. Blank falls back to the UniServe palette.">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {COLOR_FIELDS.map(({ key, label, help }) => (
            <div key={key}>
              <label className="block text-sm font-medium text-slate-700">{label}</label>
              <p className="mb-1 text-xs text-slate-500">{help}</p>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label={`${label} colour picker`}
                  value={content.colors[key]}
                  onChange={(e) => set("colors", { ...content.colors, [key]: e.target.value })}
                  className="h-9 w-10 shrink-0 cursor-pointer rounded border bg-white p-1"
                />
                <input
                  aria-label={label}
                  value={content.colors[key]}
                  placeholder={DEFAULT_LANDING_PAGE.colors[key]}
                  onChange={(e) => set("colors", { ...content.colors, [key]: e.target.value })}
                  className="w-full rounded border p-2 font-mono text-sm"
                />
              </div>
            </div>
          ))}
        </div>
        <div
          className="mt-2 flex h-16 items-center justify-end rounded-lg px-4"
          style={{
            backgroundImage: `linear-gradient(to bottom right, ${content.colors.from}, ${content.colors.via}, ${content.colors.to})`,
          }}
        >
          <span
            className="rounded-lg px-4 py-2 text-sm font-semibold text-white shadow"
            style={{
              backgroundImage: `linear-gradient(to right, ${content.colors.accent}, ${content.colors.accentTo})`,
            }}
          >
            {content.trackButtonLabel || DEFAULT_LANDING_PAGE.trackButtonLabel}
          </span>
        </div>
      </Group>

      {/* ---- Track box ---------------------------------------------- */}
      <Group title="Track your complaint box" help="The lookup form in the middle of the hero.">
        <Field
          label="Heading"
          value={content.trackHeading}
          placeholder={DEFAULT_LANDING_PAGE.trackHeading}
          onChange={(v) => set("trackHeading", v)}
        />
        <Field
          label="Help text"
          multiline
          value={content.trackHelp}
          placeholder={DEFAULT_LANDING_PAGE.trackHelp}
          help="The lookup accepts a ticket number, an ANON reference or an email — but NOT a phone number, so avoid implying that it does."
          onChange={(v) => set("trackHelp", v)}
        />
        <Field
          label="Input placeholder"
          value={content.trackPlaceholder}
          placeholder={DEFAULT_LANDING_PAGE.trackPlaceholder}
          onChange={(v) => set("trackPlaceholder", v)}
        />
        <Field
          label="Button label"
          value={content.trackButtonLabel}
          placeholder={DEFAULT_LANDING_PAGE.trackButtonLabel}
          onChange={(v) => set("trackButtonLabel", v)}
        />
        <Field
          label={'"Haven\'t filed yet" text'}
          multiline
          value={content.notFiledText}
          placeholder={DEFAULT_LANDING_PAGE.notFiledText}
          help="Name only the channels this tenant actually answers."
          onChange={(v) => set("notFiledText", v)}
        />
      </Group>

      {/* ---- Agent sign in ------------------------------------------ */}
      <Group title="Agent sign in" help="The staff link in the header, below the hero, and in the footer.">
        <Field
          label="Link label"
          value={content.agentSignInLabel}
          placeholder={DEFAULT_LANDING_PAGE.agentSignInLabel}
          onChange={(v) => set("agentSignInLabel", v)}
        />
        <Field
          label="Caption"
          value={content.agentSignInCaption}
          placeholder={DEFAULT_LANDING_PAGE.agentSignInCaption}
          onChange={(v) => set("agentSignInCaption", v)}
        />
      </Group>

      {/* ---- Fixed sections ----------------------------------------- */}
      <Group title="About us" help="First card below the hero.">
        <SectionFields
          section={content.about}
          defaults={DEFAULT_LANDING_PAGE.about}
          onChange={(s) => set("about", s)}
        />
      </Group>

      <Group title="How it works" help="Second card below the hero.">
        <SectionFields
          section={content.howItWorks}
          defaults={DEFAULT_LANDING_PAGE.howItWorks}
          onChange={(s) => set("howItWorks", s)}
        />
      </Group>

      <Group title="Contact us" help="Third card. Each detail is shown only when filled in.">
        <SectionFields
          section={content.contact}
          defaults={DEFAULT_LANDING_PAGE.contact}
          onChange={(s) => set("contact", { ...content.contact, ...s })}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          {CONTACT_FIELDS.map(({ key, label }) => (
            <Field
              key={key}
              label={label}
              value={content.contact[key]}
              placeholder="Leave blank to hide this line"
              onChange={(v) => set("contact", { ...content.contact, [key]: v })}
            />
          ))}
        </div>
      </Group>

      {/* ---- Extra sections ----------------------------------------- */}
      <Group title="Extra sections" help="Anything else this tenant wants on the page (max 10).">
        {content.sections.length === 0 && (
          <p className="text-sm text-slate-500">No extra sections yet.</p>
        )}
        {content.sections.map((section, i) => (
          <div key={i} className="rounded-lg border border-slate-200 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Section {i + 1}
              </span>
              <button
                onClick={() =>
                  set(
                    "sections",
                    content.sections.filter((_, j) => j !== i),
                  )
                }
                className="text-xs font-medium text-red-600 hover:underline"
              >
                Remove
              </button>
            </div>
            <SectionFields
              section={section}
              defaults={{ heading: "e.g. Accessibility", body: "What you want to say" }}
              onChange={(s) =>
                set(
                  "sections",
                  content.sections.map((row, j) => (j === i ? { ...row, ...s } : row)),
                )
              }
            />
          </div>
        ))}
        {content.sections.length < 10 && (
          <button
            onClick={() => set("sections", [...content.sections, { heading: "", body: "" }])}
            className="rounded border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-600 hover:border-brand-teal hover:text-brand-teal"
          >
            + Add section
          </button>
        )}
      </Group>

      {/* ---- Footer -------------------------------------------------- */}
      <Group title="Footer" help="The dark bar at the very bottom.">
        <Field
          label="Footer note"
          value={content.footerNote}
          placeholder={DEFAULT_LANDING_PAGE.footerNote}
          onChange={(v) => set("footerNote", v)}
        />
        {content.footerLinks.map((link, i) => (
          <div key={i} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Field
                label="Link label"
                value={link.label}
                placeholder="Privacy policy"
                onChange={(v) =>
                  set(
                    "footerLinks",
                    content.footerLinks.map((row, j) => (j === i ? { ...row, label: v } : row)),
                  )
                }
              />
            </div>
            <div className="flex-1">
              <Field
                label="URL"
                value={link.url}
                placeholder="/privacy, https://…, mailto:… or tel:…"
                onChange={(v) =>
                  set(
                    "footerLinks",
                    content.footerLinks.map((row, j) => (j === i ? { ...row, url: v } : row)),
                  )
                }
              />
            </div>
            <button
              onClick={() =>
                set(
                  "footerLinks",
                  content.footerLinks.filter((_, j) => j !== i),
                )
              }
              className="mb-2 shrink-0 text-xs font-medium text-red-600 hover:underline"
            >
              Remove
            </button>
          </div>
        ))}
        {content.footerLinks.length < 10 && (
          <button
            onClick={() => set("footerLinks", [...content.footerLinks, { label: "", url: "" }])}
            className="rounded border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-600 hover:border-brand-teal hover:text-brand-teal"
          >
            + Add footer link
          </button>
        )}
      </Group>
    </div>
  );
}

// ---- small building blocks -----------------------------------------

function Group({ title, help, children }: { title: string; help: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border bg-white p-4 shadow-sm">
      <div>
        <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
        <p className="text-xs text-slate-600">{help}</p>
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  value,
  placeholder,
  help,
  multiline,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  help?: string;
  multiline?: boolean;
  onChange: (value: string) => void;
}) {
  const shared = "w-full rounded border p-2 text-sm";
  return (
    <div className="mb-2">
      <label className="block text-sm font-medium text-slate-700">{label}</label>
      {help && <p className="mb-1 text-xs text-slate-500">{help}</p>}
      {multiline ? (
        <textarea
          aria-label={label}
          rows={3}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className={shared}
        />
      ) : (
        <input
          aria-label={label}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className={shared}
        />
      )}
    </div>
  );
}

function SectionFields({
  section,
  defaults,
  onChange,
}: {
  section: LandingSection;
  defaults: LandingSection;
  onChange: (section: LandingSection) => void;
}) {
  return (
    <>
      <Field
        label="Heading"
        value={section.heading}
        placeholder={defaults.heading}
        onChange={(v) => onChange({ ...section, heading: v })}
      />
      <Field
        label="Body"
        multiline
        value={section.body}
        placeholder={defaults.body}
        onChange={(v) => onChange({ ...section, body: v })}
      />
    </>
  );
}
