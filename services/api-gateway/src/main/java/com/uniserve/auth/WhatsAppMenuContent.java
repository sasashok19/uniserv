package com.uniserve.auth;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The WhatsApp conversation menu's copy and behaviour (Feature 26) — every
 * string a citizen reads on WhatsApp, held in the tenant's {@code config_json}
 * under the {@code whatsappMenu} key.
 *
 * <p>The reason this exists rather than string literals in ai-core: the welcome
 * message names the company, and the same code runs for every tenant. Before
 * this, {@code "You are the UniServe citizen complaint intake agent"} was baked
 * into a remote OpenAI Assistant object — not merely hardcoded, but hardcoded
 * <em>outside the repository</em>, so a second tenant could not be onboarded
 * without editing and re-pushing a shared Assistant.
 *
 * <p>Structured exactly like {@link LandingPageContent} — {@link #defaults()},
 * {@link #resolve}, {@link #normalise} — because ai-core reads the stored blob
 * directly from db-writer and must apply the same defaults. See
 * {@code services/ai-core/app/conversation/menu_content.py}, which mirrors
 * {@link #TEXT_DEFAULTS}; {@code test_menu_content.py} parses THIS file and
 * fails if the two ever drift.
 *
 * <p><b>Placeholders.</b> Any text field may contain {@code {company}}, which is
 * substituted at send time. The reply-composing fields may additionally use
 * {@code {ticket}}, {@code {status}}, {@code {eta}} and {@code {updated}}.
 * Substitution is plain string replacement into a plain-text WhatsApp body —
 * there is no markup, no template engine and no HTML sink here, which is why
 * these fields need length caps but not the URL/colour validation the landing
 * page needs.
 */
final class WhatsAppMenuContent {

    /** Thrown by {@link #normalise}; the message is safe to return to the admin. */
    static class InvalidContentException extends RuntimeException {
        InvalidContentException(String message) {
            super(message);
        }
    }

    private static final int MAX_SHORT = 200;
    private static final int MAX_BODY = 1000;

    /** Meta only allows free-form text within 24h of the citizen's last inbound
     * message, so a session may never outlive that window — past it the next
     * send fails at the Graph API regardless of what our state says. */
    static final int MAX_SESSION_TTL_HOURS = 24;
    static final int DEFAULT_SESSION_TTL_HOURS = 12;

    /** Meta caps an interactive reply-button title at 20 characters, and rejects
     * the whole send if one is longer — so the citizen would receive nothing at
     * all. Enforced on write here and clamped again on read/send in ai-core. */
    static final int MAX_BUTTON_LABEL = 20;

    /** The three option labels, which become the reply buttons. */
    private static final List<String> BUTTON_LABELS =
            List.of("option1Label", "option2Label", "option3Label");

    /** Text fields: key -> default. Order here is the order the admin panel shows them. */
    private static final Map<String, String> TEXT_DEFAULTS = new LinkedHashMap<>();

    static {
        TEXT_DEFAULTS.put("companyName", "");
        TEXT_DEFAULTS.put("welcome", "Welcome to {company}!");
        TEXT_DEFAULTS.put("menuPrompt",
                "Please choose an option:\n"
                        + "Press 1 to know the status, ETA and last update for an existing ticket.\n"
                        + "Press 2 to register a new ticket.\n"
                        + "Press 3 to end this chat.");
        TEXT_DEFAULTS.put("menuIntro", "Please choose an option:");
        TEXT_DEFAULTS.put("option1Label", "Ticket status");
        TEXT_DEFAULTS.put("option2Label", "New ticket");
        TEXT_DEFAULTS.put("option3Label", "End chat");
        TEXT_DEFAULTS.put("menuHint", "You can press # at any time to return to the main menu.");
        TEXT_DEFAULTS.put("unknownOption",
                "Sorry, I didn't catch that. Please reply with 1, 2 or 3.");
        TEXT_DEFAULTS.put("askTicketId",
                "Please share your Ticket ID (for example TKT-00042).");
        TEXT_DEFAULTS.put("ticketNotFound",
                "I couldn't find a ticket with that ID against this number. "
                        + "Please check the Ticket ID and send it again.");
        TEXT_DEFAULTS.put("ticketDetails",
                "Ticket {ticket}\nComplaint: {complaint}\nStatus: {status}\nETA: {eta}"
                        + "\nLast updated: {updated}");
        TEXT_DEFAULTS.put("inviteNote",
                "If you have any questions, or would like to add anything to this ticket, "
                        + "you can type your message here and I'll add it to the ticket.");
        TEXT_DEFAULTS.put("noteAdded",
                "Thank you — your note has been added to ticket {ticket} and the team will revert on it.");
        TEXT_DEFAULTS.put("registerIntro",
                "Sure, let's register a new ticket. Please reply with the following details:");
        TEXT_DEFAULTS.put("ticketCreated",
                "Your ticket has been registered.\nTicket {ticket}\nComplaint: {complaint}"
                        + "\nStatus: {status}\nETA: {eta}");
        TEXT_DEFAULTS.put("conversationEnd",
                "We're ending this conversation here. Send us any message whenever you need us "
                        + "and the main menu will open again.");
        TEXT_DEFAULTS.put("farewell", "Thanks for reaching out. Have a great time");
        TEXT_DEFAULTS.put("etaUnknown", "not set yet");
        TEXT_DEFAULTS.put("complaintUnknown", "not summarised yet");
        TEXT_DEFAULTS.put("duplicateAsk",
                "Before I raise a new ticket — we already have ticket {ticket} open for "
                        + "\"{existing}\". {question}");
        TEXT_DEFAULTS.put("duplicateMerged",
                "Thanks for confirming. I've added your message to the existing ticket {ticket} "
                        + "rather than raising a duplicate.\nComplaint: {complaint}"
                        + "\nStatus: {status}\nETA: {eta}");
    }

    /** Fields long enough to need the body cap rather than the short one. */
    private static final List<String> LONG_FIELDS = List.of(
            "menuPrompt", "ticketNotFound", "ticketDetails", "inviteNote", "noteAdded",
            "registerIntro", "ticketCreated", "conversationEnd", "duplicateAsk", "duplicateMerged");

    private WhatsAppMenuContent() {
    }

    // ---- defaults ----------------------------------------------------

    /** A complete, sendable menu — what a tenant that configures nothing gets. */
    static Map<String, Object> defaults() {
        Map<String, Object> out = new LinkedHashMap<>(TEXT_DEFAULTS);
        out.put("enabled", Boolean.TRUE);
        out.put("useInteractiveButtons", Boolean.TRUE);
        out.put("sessionTtlHours", DEFAULT_SESSION_TTL_HOURS);
        return out;
    }

    // ---- read --------------------------------------------------------

    /**
     * The tenant's stored menu laid over {@link #defaults()}. A field left blank
     * reads as its default rather than as an empty message — a blank welcome
     * would otherwise send the citizen an empty WhatsApp message.
     *
     * <p>{@code companyName} is the one field with a cascade rather than a
     * literal default: it falls back to the landing page's {@code brandName},
     * so a tenant that has already branded its public page does not have to
     * type its own name a second time to brand WhatsApp.
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> resolve(Map<String, Object> config) {
        Map<String, Object> out = defaults();
        Object raw = config == null ? null : config.get("whatsappMenu");
        Map<String, Object> stored = raw instanceof Map ? (Map<String, Object>) raw : Map.of();

        for (String key : TEXT_DEFAULTS.keySet()) {
            String v = str(stored.get(key));
            if (!v.isEmpty()) {
                out.put(key, v);
            }
        }
        if (str(out.get("companyName")).isEmpty()) {
            out.put("companyName", brandName(config));
        }

        for (String flag : List.of("enabled", "useInteractiveButtons")) {
            Object value = stored.get(flag);
            if (value instanceof Boolean b) {
                out.put(flag, b);
            } else if (value != null) {
                out.put(flag, Boolean.parseBoolean(String.valueOf(value)));
            }
        }
        // Clamped on read too: a label that reached the blob without passing
        // normalise() would make every interactive send fail outright.
        for (String key : BUTTON_LABELS) {
            String label = str(out.get(key));
            out.put(key, label.length() > MAX_BUTTON_LABEL
                    ? label.substring(0, MAX_BUTTON_LABEL) : label);
        }

        // Re-clamped on READ, not just on write: TenantConfigResource replaces
        // the whole config_json blob, so a whatsappMenu object can reach the
        // database without ever passing through normalise().
        out.put("sessionTtlHours", clampTtl(stored.get("sessionTtlHours"), DEFAULT_SESSION_TTL_HOURS));
        return out;
    }

    /** The tenant's brand name from the landing-page config, or the product name. */
    private static String brandName(Map<String, Object> config) {
        Map<String, Object> landing = LandingPageContent.resolve(config);
        String brand = str(landing.get("brandName"));
        return brand.isEmpty() ? "UniServe" : brand;
    }

    // ---- write -------------------------------------------------------

    /**
     * Validate and clean an admin-submitted body into the object we persist.
     * Unknown keys are dropped; blank strings are kept (blank means "use the
     * default", which {@link #resolve} then supplies).
     *
     * @throws InvalidContentException with an admin-readable message
     */
    static Map<String, Object> normalise(Map<String, Object> body) {
        if (body == null) {
            throw new InvalidContentException("Request body is required");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        for (String key : TEXT_DEFAULTS.keySet()) {
            out.put(key, checked(body.get(key), key, LONG_FIELDS.contains(key) ? MAX_BODY : MAX_SHORT));
        }

        // The menu is what tells a citizen an option exists, so a menuPrompt
        // that has lost one of its numbers leaves that branch unreachable in
        // practice while still working if typed. Caught here rather than left
        // to a support ticket about "option 3 doesn't exist".
        String prompt = str(out.get("menuPrompt"));
        if (!prompt.isEmpty()) {
            for (String option : List.of("1", "2", "3")) {
                if (!prompt.contains(option)) {
                    throw new InvalidContentException(
                            "'menuPrompt' must still offer option " + option
                                    + " — the citizen has no other way to discover it");
                }
            }
        }
        // {ticket} is the citizen's only handle on their complaint; a details
        // template without it reads out a status with nothing to attach it to.
        for (String key : List.of("ticketDetails", "ticketCreated")) {
            String template = str(out.get(key));
            if (!template.isEmpty() && !template.contains("{ticket}")) {
                throw new InvalidContentException("'" + key + "' must include the {ticket} placeholder");
            }
        }

        // A button label longer than Meta's cap fails the whole send, so this is
        // rejected on the admin screen rather than silently clipped — the admin
        // is the only one who can choose a shorter wording that still reads well.
        for (String key : BUTTON_LABELS) {
            String label = str(out.get(key));
            if (label.length() > MAX_BUTTON_LABEL) {
                throw new InvalidContentException(
                        "'" + key + "' must be at most " + MAX_BUTTON_LABEL + " characters — "
                                + "WhatsApp rejects a longer button label, and the citizen would "
                                + "then receive no menu at all");
            }
        }

        for (String flag : List.of("enabled", "useInteractiveButtons")) {
            Object value = body.get(flag);
            out.put(flag, value == null || Boolean.parseBoolean(String.valueOf(value))
                    || Boolean.TRUE.equals(value));
        }

        Object ttl = body.get("sessionTtlHours");
        if (ttl != null && !str(ttl).isEmpty()) {
            int parsed;
            try {
                parsed = (int) Double.parseDouble(str(ttl));
            } catch (NumberFormatException e) {
                throw new InvalidContentException("'sessionTtlHours' must be a whole number of hours");
            }
            if (parsed < 1 || parsed > MAX_SESSION_TTL_HOURS) {
                throw new InvalidContentException(
                        "'sessionTtlHours' must be between 1 and " + MAX_SESSION_TTL_HOURS
                                + " — WhatsApp only permits a free-form reply within 24h of the "
                                + "citizen's last message, so a longer session could never be answered");
            }
            out.put("sessionTtlHours", parsed);
        } else {
            out.put("sessionTtlHours", DEFAULT_SESSION_TTL_HOURS);
        }
        return out;
    }

    // ---- helpers -----------------------------------------------------

    private static int clampTtl(Object raw, int fallback) {
        if (raw == null) {
            return fallback;
        }
        try {
            int v = (int) Double.parseDouble(String.valueOf(raw));
            if (v < 1 || v > MAX_SESSION_TTL_HOURS) {
                return fallback;
            }
            return v;
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static String checked(Object raw, String field, int max) {
        String v = str(raw);
        if (v.length() > max) {
            throw new InvalidContentException(
                    "'" + field + "' must be at most " + max + " characters");
        }
        return v;
    }

    private static String str(Object raw) {
        return raw == null ? "" : String.valueOf(raw).trim();
    }
}
