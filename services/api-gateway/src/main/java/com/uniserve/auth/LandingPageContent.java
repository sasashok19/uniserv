package com.uniserve.auth;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * The public landing page's text, logo and palette (Feature 25) — every string
 * a citizen sees on {@code /}, held in the tenant's {@code config_json} under
 * the {@code landingPage} key so a new tenant is re-worded from the admin
 * screen rather than by editing {@code page.tsx}.
 *
 * <p>Two resources share this class: {@link LandingPageResource} (admin,
 * read/write) and {@link PublicLandingPageResource} (no auth, read-only). It
 * owns three things so those two can never disagree:
 *
 * <ol>
 *   <li>{@link #defaults()} — the copy currently hardcoded in the dashboard.
 *       Every unset field falls back here, so a tenant that configures nothing
 *       still gets a complete, sensible page.</li>
 *   <li>{@link #resolve} — defaults merged with what the tenant stored.</li>
 *   <li>{@link #normalise} — validation for the PUT path.</li>
 * </ol>
 *
 * <p><b>Why validation is not cosmetic here.</b> Two of these fields leave the
 * realm of "text React will escape for us":
 * <ul>
 *   <li>{@code colors.*} are interpolated into a {@code style} attribute. Only
 *       {@code #RGB}/{@code #RRGGBB} is accepted — a free-form string there
 *       would let an admin inject arbitrary CSS into a page every citizen
 *       loads unauthenticated.</li>
 *   <li>{@code logoUrl} and {@code footerLinks[].url} become {@code src}/
 *       {@code href}. Only same-origin paths ({@code /logo.png}), {@code http(s)},
 *       and — for links only — {@code mailto:}/{@code tel:} are accepted, which
 *       is what rejects {@code javascript:}. Protocol-relative {@code //host}
 *       is rejected too: it looks same-origin but isn't.</li>
 * </ul>
 * Body/heading text needs no such treatment because the dashboard renders it as
 * text nodes, never {@code dangerouslySetInnerHTML} — keep it that way.
 */
final class LandingPageContent {

    /** Thrown by {@link #normalise}; the message is safe to return to the admin. */
    static class InvalidContentException extends RuntimeException {
        InvalidContentException(String message) {
            super(message);
        }
    }

    // Length caps. Generous enough for real copy, tight enough that config_json
    // stays a config blob rather than a CMS.
    private static final int MAX_SHORT = 200;
    private static final int MAX_HEADING = 120;
    private static final int MAX_BODY = 2000;
    private static final int MAX_URL = 500;
    private static final int MAX_EXTRA_SECTIONS = 10;
    private static final int MAX_FOOTER_LINKS = 10;

    private static final Pattern HEX_COLOR = Pattern.compile("^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$");

    /** Simple string fields: key -> default. Order here is the order the admin panel shows them. */
    private static final Map<String, String> TEXT_DEFAULTS = new LinkedHashMap<>();
    /** The three always-present sections, in render order. */
    static final List<String> FIXED_SECTIONS = List.of("about", "howItWorks", "contact");
    /** Palette keys: three gradient stops for the page, two for the CTA button. */
    static final List<String> COLOR_KEYS = List.of("from", "via", "to", "accent", "accentTo");

    static {
        TEXT_DEFAULTS.put("brandName", "UniServe");
        TEXT_DEFAULTS.put("tagline", "The complaint that gets heard.");
        TEXT_DEFAULTS.put("subTagline", "Multi-tenant AI-powered complaint & feedback portal");
        TEXT_DEFAULTS.put("trackHeading", "Track your complaint");
        TEXT_DEFAULTS.put("trackHelp",
                "Enter your ticket number (e.g. TKT-00042), your ANON-XXXX reference, "
                        + "or the email address you wrote in from.");
        TEXT_DEFAULTS.put("trackPlaceholder", "TKT-00042, ANON-1234, or you@example.com");
        TEXT_DEFAULTS.put("trackButtonLabel", "Track complaint");
        TEXT_DEFAULTS.put("notFiledText",
                "Haven't filed a complaint yet? Reach us by Email or WhatsApp and we'll take it from there.");
        TEXT_DEFAULTS.put("agentSignInLabel", "Agent sign in");
        TEXT_DEFAULTS.put("agentSignInCaption", "For UniServe staff and support agents");
        TEXT_DEFAULTS.put("footerNote", "UniServe — multi-tenant complaint & feedback portal");
    }

    private LandingPageContent() {
    }

    // ---- defaults ----------------------------------------------------

    /** A complete, renderable content object — the copy the page shipped with. */
    static Map<String, Object> defaults() {
        Map<String, Object> out = new LinkedHashMap<>(TEXT_DEFAULTS);
        out.put("logoUrl", "");
        // accent/accentTo are the two stops of the "Track complaint" button's
        // gradient. Two rather than one purely so the default palette renders
        // the page exactly as it looked before it became configurable.
        out.put("colors", new LinkedHashMap<>(Map.of(
                "from", "#0D1B2A",
                "via", "#1B3A52",
                "to", "#028090",
                "accent", "#F4A261",
                "accentTo", "#E07B54")));
        out.put("about", section("About us",
                "We are here to make sure every complaint reaches a person who can act on it, "
                        + "and that you can see what happened to it."));
        out.put("howItWorks", section("How it works",
                "Write to us by email or WhatsApp in your own words. We read it, route it to the "
                        + "right team, and give you a reference number you can track on this page."));
        Map<String, Object> contact = section("Contact us",
                "Reach us any way that suits you — we will reply on the same channel.");
        contact.put("email", "");
        contact.put("phone", "");
        contact.put("whatsapp", "");
        contact.put("address", "");
        contact.put("hours", "");
        out.put("contact", contact);
        out.put("sections", new ArrayList<Map<String, Object>>());
        out.put("footerLinks", new ArrayList<Map<String, Object>>());
        return out;
    }

    private static Map<String, Object> section(String heading, String body) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("heading", heading);
        s.put("body", body);
        return s;
    }

    // ---- read --------------------------------------------------------

    /**
     * The tenant's stored content laid over {@link #defaults()}. A field the
     * tenant never set — or set to something we no longer accept — reads as its
     * default rather than as blank, so a half-filled config still renders.
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> resolve(Map<String, Object> config) {
        Map<String, Object> out = defaults();
        Object raw = config == null ? null : config.get("landingPage");
        if (!(raw instanceof Map)) {
            return out;
        }
        Map<String, Object> stored = (Map<String, Object>) raw;

        for (String key : TEXT_DEFAULTS.keySet()) {
            String v = str(stored.get(key));
            if (!v.isEmpty()) {
                out.put(key, v);
            }
        }
        // logoUrl is the one string whose blank IS meaningful (no logo), so it
        // is merged unconditionally rather than only-when-non-empty. Re-checked
        // here and not just in normalise(): TenantConfigResource replaces the
        // whole config_json blob, so a landingPage object can reach the DB
        // without ever passing through this class's PUT path.
        String logoUrl = str(stored.get("logoUrl"));
        out.put("logoUrl", isSafeImageUrl(logoUrl) ? logoUrl : "");

        if (stored.get("colors") instanceof Map<?, ?> storedColors) {
            Map<String, Object> colors = (Map<String, Object>) out.get("colors");
            for (String key : COLOR_KEYS) {
                String v = str(storedColors.get(key));
                if (HEX_COLOR.matcher(v).matches()) {
                    colors.put(key, v);
                }
            }
        }

        for (String key : FIXED_SECTIONS) {
            if (stored.get(key) instanceof Map<?, ?> storedSection) {
                Map<String, Object> target = (Map<String, Object>) out.get(key);
                for (Map.Entry<String, Object> e : target.entrySet()) {
                    Object v = storedSection.get(e.getKey());
                    if (v != null) {
                        e.setValue(str(v));
                    }
                }
            }
        }

        if (stored.get("sections") instanceof List<?> list) {
            List<Map<String, Object>> extras = new ArrayList<>();
            for (Object o : list) {
                if (o instanceof Map<?, ?> m) {
                    String heading = str(m.get("heading"));
                    String body = str(m.get("body"));
                    if (!heading.isEmpty() || !body.isEmpty()) {
                        extras.add(section(heading, body));
                    }
                }
            }
            out.put("sections", extras);
        }

        if (stored.get("footerLinks") instanceof List<?> list) {
            List<Map<String, Object>> links = new ArrayList<>();
            for (Object o : list) {
                if (o instanceof Map<?, ?> m) {
                    String label = str(m.get("label"));
                    String url = str(m.get("url"));
                    if (!label.isEmpty() && isSafeLinkUrl(url)) {
                        links.add(new LinkedHashMap<>(Map.of("label", label, "url", url)));
                    }
                }
            }
            out.put("footerLinks", links);
        }

        return out;
    }

    // ---- write -------------------------------------------------------

    /**
     * Validate and clean an admin-submitted body into the object we persist.
     * Unknown keys are dropped; blank strings are kept (an admin clearing a
     * field means "use the default", which {@link #resolve} then supplies).
     *
     * @throws InvalidContentException with an admin-readable message
     */
    static Map<String, Object> normalise(Map<String, Object> body) {
        if (body == null) {
            throw new InvalidContentException("Request body is required");
        }
        Map<String, Object> out = new LinkedHashMap<>();

        for (String key : TEXT_DEFAULTS.keySet()) {
            int cap = key.equals("trackHelp") || key.equals("notFiledText") ? MAX_BODY : MAX_SHORT;
            out.put(key, checked(body.get(key), key, cap));
        }

        String logoUrl = checked(body.get("logoUrl"), "logoUrl", MAX_URL);
        if (!logoUrl.isEmpty() && !isSafeImageUrl(logoUrl)) {
            throw new InvalidContentException(
                    "'logoUrl' must be a same-origin path starting with '/' (e.g. /tenants/acme/logo.png) "
                            + "or an http(s) URL");
        }
        out.put("logoUrl", logoUrl);

        Map<String, Object> colors = new LinkedHashMap<>();
        Object rawColors = body.get("colors");
        Map<?, ?> submittedColors = rawColors instanceof Map<?, ?> m ? m : Map.of();
        for (String key : COLOR_KEYS) {
            String v = str(submittedColors.get(key));
            if (v.isEmpty()) {
                continue; // blank -> fall back to the UniServe palette on read
            }
            if (!HEX_COLOR.matcher(v).matches()) {
                throw new InvalidContentException(
                        "'colors." + key + "' must be a hex colour such as #0D1B2A");
            }
            colors.put(key, v);
        }
        out.put("colors", colors);

        for (String key : FIXED_SECTIONS) {
            Object raw = body.get(key);
            Map<?, ?> submitted = raw instanceof Map<?, ?> m ? m : Map.of();
            Map<String, Object> section = new LinkedHashMap<>();
            section.put("heading", checked(submitted.get("heading"), key + ".heading", MAX_HEADING));
            section.put("body", checked(submitted.get("body"), key + ".body", MAX_BODY));
            if (key.equals("contact")) {
                for (String field : List.of("email", "phone", "whatsapp", "address", "hours")) {
                    section.put(field, checked(submitted.get(field), "contact." + field, MAX_SHORT));
                }
            }
            out.put(key, section);
        }

        List<Map<String, Object>> extras = new ArrayList<>();
        if (body.get("sections") instanceof List<?> list) {
            if (list.size() > MAX_EXTRA_SECTIONS) {
                throw new InvalidContentException("At most " + MAX_EXTRA_SECTIONS + " extra sections are allowed");
            }
            for (Object o : list) {
                Map<?, ?> m = o instanceof Map<?, ?> mm ? mm : Map.of();
                String heading = checked(m.get("heading"), "sections[].heading", MAX_HEADING);
                String bodyText = checked(m.get("body"), "sections[].body", MAX_BODY);
                if (heading.isEmpty() && bodyText.isEmpty()) {
                    continue; // an empty row the admin added but never filled in
                }
                if (heading.isEmpty()) {
                    throw new InvalidContentException("Every extra section needs a heading");
                }
                extras.add(section(heading, bodyText));
            }
        }
        out.put("sections", extras);

        List<Map<String, Object>> links = new ArrayList<>();
        if (body.get("footerLinks") instanceof List<?> list) {
            if (list.size() > MAX_FOOTER_LINKS) {
                throw new InvalidContentException("At most " + MAX_FOOTER_LINKS + " footer links are allowed");
            }
            for (Object o : list) {
                Map<?, ?> m = o instanceof Map<?, ?> mm ? mm : Map.of();
                String label = checked(m.get("label"), "footerLinks[].label", MAX_SHORT);
                String url = checked(m.get("url"), "footerLinks[].url", MAX_URL);
                if (label.isEmpty() && url.isEmpty()) {
                    continue;
                }
                if (label.isEmpty() || url.isEmpty()) {
                    throw new InvalidContentException("Every footer link needs both a label and a URL");
                }
                if (!isSafeLinkUrl(url)) {
                    throw new InvalidContentException(
                            "Footer link '" + label + "' must be an http(s), mailto:, tel: or '/' URL");
                }
                links.add(new LinkedHashMap<>(Map.of("label", label, "url", url)));
            }
        }
        out.put("footerLinks", links);

        return out;
    }

    // ---- helpers -----------------------------------------------------

    /**
     * A tenant row's {@code config_json} as a mutable map. Unparseable or
     * absent config reads as empty rather than throwing: for the public
     * endpoint that means "serve the defaults", and for the admin endpoint it
     * means the next save rewrites the broken blob rather than being blocked
     * by it.
     */
    static Map<String, Object> parseConfig(com.fasterxml.jackson.databind.ObjectMapper mapper, Object raw) {
        if (raw == null) {
            return new LinkedHashMap<>();
        }
        try {
            Map<String, Object> parsed = mapper.readValue(String.valueOf(raw),
                    new com.fasterxml.jackson.core.type.TypeReference<>() {
                    });
            return new LinkedHashMap<>(parsed);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    /**
     * {@code /path} (but not {@code //host}, which is protocol-relative and
     * therefore off-origin) or an absolute http(s) URL.
     */
    private static boolean isSafeImageUrl(String url) {
        if (url.startsWith("//")) {
            return false;
        }
        return url.startsWith("/") || url.startsWith("http://") || url.startsWith("https://");
    }

    /** As {@link #isSafeImageUrl}, plus the two link-only schemes. */
    private static boolean isSafeLinkUrl(String url) {
        return isSafeImageUrl(url) || url.startsWith("mailto:") || url.startsWith("tel:");
    }

    private static String checked(Object raw, String field, int max) {
        String value = str(raw);
        if (value.length() > max) {
            throw new InvalidContentException("'" + field + "' must be at most " + max + " characters");
        }
        return value;
    }

    /** Null-safe trim. Non-strings are stringified rather than rejected — a
     *  number typed into a text box is the admin's intent, not an error. */
    private static String str(Object raw) {
        return raw == null ? "" : String.valueOf(raw).trim();
    }
}
