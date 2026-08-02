package com.uniserve.auth;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Public citizen-portal status lookup (Feature 12): {@code GET /api/v1/public/status/{ref}}.
 * No authentication. {@code ref} is an ANON-XXXX reference, an email, or (Feature 18b) a
 * {@code TKT-XXXXX} ticket number. Returns only non-PII ticket status information.
 */
@Path("/api/v1/public/status")
@Produces(MediaType.APPLICATION_JSON)
public class PublicStatusResource {

    // Matches ai-core's own TICKET_NUMBER_RE (app/tickets/intake.py) — kept
    // case-insensitive here since this is direct citizen-typed input (a
    // subject line/message body is never hand-typed, so ai-core's version
    // doesn't need to bother).
    private static final Pattern TICKET_NUMBER = Pattern.compile("TKT-\\d{4,}", Pattern.CASE_INSENSITIVE);

    @Inject
    DbWriterClient db;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String defaultTenant;

    @GET
    @Path("/{ref}")
    public Response status(@PathParam("ref") String ref) {
        // Feature 18b: a ticket number is the ONE identifier every citizen
        // is actually given prominently (every ack email/WhatsApp message
        // says "Ticket ID: TKT-XXXXX") — unlike an ANON-XXXX ref (opt-in,
        // anonymous citizens only) or an email (has to match exactly), this
        // is what most citizens will naturally try first. Previously this
        // fell through to the ANON-ref branch below, which can never match
        // a ticket number, so it silently 404'd despite the ticket existing.
        if (TICKET_NUMBER.matcher(ref).matches()) {
            return statusByTicketNumber(ref);
        }

        Optional<Map<String, Object>> profile = ref.contains("@")
                ? db.findIdentityByEmail(defaultTenant, ref)
                : db.findIdentityByAnonRef(ref);

        if (profile.isEmpty()) {
            return notFound(ref);
        }

        Map<String, Object> p = profile.get();
        String tenantId = String.valueOf(p.get("tenant_id"));
        // tickets.identity_id is populated with the profile's masterId (see
        // ai-core's identity resolver, Feature 03), not its primary key.
        String identityId = String.valueOf(p.get("master_id"));

        List<Map<String, Object>> tickets = db.listTickets(
                "tenantId=" + enc(tenantId) + "&identityId=" + enc(identityId));
        return ok(ref, intOf(p.get("is_anonymous")) == 1, tickets);
    }

    /** Resolve by ticket number, then expand to every ticket under the SAME
     * identity — consistent with the email/anon-ref paths, which always show
     * a citizen's full ticket history, not just the one they looked up. Falls
     * back to just the matched ticket if it has no identity linked yet
     * (still in the intake/pending stage). */
    private Response statusByTicketNumber(String ticketNumber) {
        // db-writer's /api/v1/db/tickets requires tenantId (400 TENANT_REQUIRED
        // otherwise) -- this is a cross-tenant citizen lookup by ticket number
        // alone, so we scan with the gateway's own default tenant rather than
        // one derived from the (not yet known) ticket.
        List<Map<String, Object>> matches = db.listTickets(
                "tenantId=" + enc(defaultTenant) + "&ticketNumber=" + enc(ticketNumber));
        if (matches.isEmpty()) {
            return notFound(ticketNumber);
        }
        Map<String, Object> matched = matches.get(0);
        // NOTE: TicketService.list()'s projection (LIST_COLUMNS) does not
        // include tenant_id (unlike the single-ticket GET, which uses
        // Ticket#toMap()) -- reading matched.get("tenant_id") here previously
        // always returned null, silently producing zero expanded results.
        // This lookup only ever runs against the gateway's own tenant anyway.
        Object identityId = matched.get("identity_id");

        List<Map<String, Object>> tickets = (identityId != null)
                ? db.listTickets("tenantId=" + enc(defaultTenant) + "&identityId=" + enc(String.valueOf(identityId)))
                : matches;
        return ok(ticketNumber, false, tickets);
    }

    private static Response ok(String ref, boolean isAnonymous, List<Map<String, Object>> tickets) {
        List<Map<String, Object>> publicTickets = new ArrayList<>();
        for (Map<String, Object> t : tickets) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("ticketNumber", t.get("ticket_number"));
            view.put("status", t.get("status"));
            view.put("category", t.get("category"));
            view.put("lastUpdated", t.get("updated_at"));
            publicTickets.add(view);
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ref", ref);
        body.put("isAnonymous", isAnonymous);
        body.put("tickets", publicTickets);
        return Response.ok(body).build();
    }

    private static Response notFound(String ref) {
        return Response.status(404).entity(Map.of("error", Map.of(
                "code", "NOT_FOUND", "message", "No record found for reference " + ref))).build();
    }

    private static int intOf(Object v) {
        return v instanceof Number n ? n.intValue() : 0;
    }

    private static String enc(String v) {
        return URLEncoder.encode(v, StandardCharsets.UTF_8);
    }
}
