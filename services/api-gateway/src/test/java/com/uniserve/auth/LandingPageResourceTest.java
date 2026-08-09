package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link LandingPageResource}, {@link PublicLandingPageResource}
 * and the {@link LandingPageContent} rules they share (Feature 25).
 *
 * <p>The two behaviours worth stating up front, because both are load-bearing
 * for a tenant re-brand: an unset field must read as its DEFAULT (never blank,
 * or a half-configured tenant ships an empty page), and a save must preserve
 * the rest of {@code config_json} (or re-wording the landing page silently
 * destroys the tenant's categories and SLA targets).
 */
class LandingPageResourceTest {

    private DbWriterClient db;
    private ObjectMapper mapper;
    private LandingPageResource resource;
    private CurrentUser admin;

    @BeforeEach
    void setUp() {
        db = mock(DbWriterClient.class);
        mapper = new ObjectMapper();
        admin = new CurrentUser();
        admin.set("a-1", "t1", "admin", "Admin", "admin@example.com");
        resource = new LandingPageResource();
        resource.db = db;
        resource.mapper = mapper;
        resource.user = admin;
    }

    private void tenantConfig(String configJson) {
        Map<String, Object> tenant = new LinkedHashMap<>();
        tenant.put("id", "t1");
        tenant.put("config_json", configJson);
        when(db.getTenant("t1")).thenReturn(tenant);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> content(Response response) {
        return (Map<String, Object>) ((Map<String, Object>) response.getEntity()).get("content");
    }

    // ---- read --------------------------------------------------------

    @Test
    void getReturnsCompleteDefaultsWhenTenantHasNoConfig() {
        tenantConfig(null);

        Response response = resource.get();

        assertEquals(200, response.getStatus());
        Map<String, Object> content = content(response);
        assertEquals("UniServe", content.get("brandName"));
        assertEquals("The complaint that gets heard.", content.get("tagline"));
        assertEquals("Track your complaint", content.get("trackHeading"));
        assertEquals("Agent sign in", content.get("agentSignInLabel"));
        // The fixed sections must be present and non-empty, not just declared.
        for (String key : LandingPageContent.FIXED_SECTIONS) {
            @SuppressWarnings("unchecked")
            Map<String, Object> section = (Map<String, Object>) content.get(key);
            assertFalse(String.valueOf(section.get("heading")).isBlank(), key + " needs a default heading");
            assertFalse(String.valueOf(section.get("body")).isBlank(), key + " needs a default body");
        }
    }

    @Test
    void getSurvivesUnparseableConfigJson() {
        tenantConfig("{not valid json");

        Response response = resource.get();

        assertEquals(200, response.getStatus());
        assertEquals("UniServe", content(response).get("brandName"));
    }

    @Test
    void storedContentLaysOverDefaultsFieldByField() {
        // Only the tagline is configured: everything else must still resolve.
        tenantConfig("{\"landingPage\":{\"tagline\":\"Your voice, heard.\"}}");

        Map<String, Object> content = content(resource.get());

        assertEquals("Your voice, heard.", content.get("tagline"));
        assertEquals("Track your complaint", content.get("trackHeading"));
        assertEquals("UniServe", content.get("brandName"));
    }

    @Test
    void blankStoredStringFallsBackToItsDefault() {
        // An admin clearing a box means "use the default", not "render nothing".
        tenantConfig("{\"landingPage\":{\"tagline\":\"   \",\"brandName\":\"\"}}");

        Map<String, Object> content = content(resource.get());

        assertEquals("The complaint that gets heard.", content.get("tagline"));
        assertEquals("UniServe", content.get("brandName"));
    }

    @Test
    void getIsForbiddenForNonAdmins() {
        CurrentUser agent = new CurrentUser();
        agent.set("a-2", "t1", "agent", "Agent", "agent@example.com");
        resource.user = agent;

        assertEquals(403, resource.get().getStatus());
        assertEquals(403, resource.update(Map.of("brandName", "Acme")).getStatus());
        verify(db, never()).updateTenantConfig(anyString(), anyString());
    }

    // ---- write -------------------------------------------------------

    @Test
    @SuppressWarnings("unchecked")
    void saveKeepsTheRestOfTenantConfigIntact() throws Exception {
        // The regression that would hurt most: re-wording the landing page must
        // not drop categories/SLA/generalSettings from the same config blob.
        tenantConfig("{\"categories\":[\"outage\",\"billing\"],"
                + "\"generalSettings\":{\"maxFollowupQuestions\":3},"
                + "\"slaTargets\":{\"high\":4}}");

        Response response = resource.update(Map.of("brandName", "Acme Water Board"));

        assertEquals(200, response.getStatus());
        ArgumentCaptor<String> json = ArgumentCaptor.forClass(String.class);
        verify(db).updateTenantConfig(org.mockito.ArgumentMatchers.eq("t1"), json.capture());
        Map<String, Object> written = mapper.readValue(json.getValue(), Map.class);
        assertEquals(List.of("outage", "billing"), written.get("categories"));
        assertEquals(Map.of("maxFollowupQuestions", 3), written.get("generalSettings"));
        assertEquals(Map.of("high", 4), written.get("slaTargets"));
        assertEquals("Acme Water Board",
                ((Map<String, Object>) written.get("landingPage")).get("brandName"));
    }

    @Test
    void saveEchoesTheResolvedViewNotTheSubmittedBody() {
        tenantConfig("{}");

        // Only brandName submitted -- the response must still carry every other
        // field, so the admin panel repaints with the defaults that filled in.
        Map<String, Object> content = content(resource.update(Map.of("brandName", "Acme")));

        assertEquals("Acme", content.get("brandName"));
        assertEquals("Track your complaint", content.get("trackHeading"));
    }

    // ---- colours: these reach a style attribute, so they are strict ----

    @Test
    void saveRejectsAColourThatIsNotHex() {
        tenantConfig("{}");

        Response response = resource.update(Map.of(
                "brandName", "Acme",
                "colors", Map.of("from", "red; background: url(javascript:alert(1))")));

        assertEquals(422, response.getStatus());
        verify(db, never()).updateTenantConfig(anyString(), anyString());
    }

    @Test
    void saveAcceptsThreeAndSixDigitHexColours() {
        tenantConfig("{}");

        Response response = resource.update(Map.of(
                "brandName", "Acme",
                "colors", Map.of("from", "#123", "via", "#1B3A52", "to", "#abcdef", "accent", "#FFF")));

        assertEquals(200, response.getStatus());
    }

    @Test
    @SuppressWarnings("unchecked")
    void aBlankColourFallsBackToTheUniservePalette() {
        tenantConfig("{}");

        Map<String, Object> content = content(resource.update(Map.of(
                "brandName", "Acme",
                "colors", Map.of("from", "", "accent", "#112233"))));

        Map<String, Object> colors = (Map<String, Object>) content.get("colors");
        assertEquals("#0D1B2A", colors.get("from"));
        assertEquals("#112233", colors.get("accent"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void aNonHexColourWrittenAroundTheValidatorIsIgnoredOnRead() {
        // TenantConfigResource replaces the whole config blob, so a landingPage
        // object can reach the DB without passing through normalise().
        tenantConfig("{\"landingPage\":{\"colors\":{\"from\":\"red;}body{display:none\"}}}");

        Map<String, Object> colors = (Map<String, Object>) content(resource.get()).get("colors");

        assertEquals("#0D1B2A", colors.get("from"));
    }

    // ---- logo + links: these reach src/href ---------------------------

    @Test
    void saveAcceptsACommittedPathAndAnAbsoluteUrl() {
        tenantConfig("{}");
        assertEquals(200, resource.update(Map.of(
                "brandName", "Acme", "logoUrl", "/tenants/acme/logo.png")).getStatus());
        assertEquals(200, resource.update(Map.of(
                "brandName", "Acme", "logoUrl", "https://acme.example/logo.svg")).getStatus());
    }

    @Test
    void saveRejectsAJavascriptLogoUrl() {
        tenantConfig("{}");

        Response response = resource.update(Map.of(
                "brandName", "Acme", "logoUrl", "javascript:alert(1)"));

        assertEquals(422, response.getStatus());
    }

    @Test
    void saveRejectsAProtocolRelativeLogoUrl() {
        // "//evil.example/logo.png" reads as same-origin but is not.
        tenantConfig("{}");

        assertEquals(422, resource.update(Map.of(
                "brandName", "Acme", "logoUrl", "//evil.example/logo.png")).getStatus());
    }

    @Test
    void anUnsafeLogoWrittenAroundTheValidatorIsDroppedOnRead() {
        tenantConfig("{\"landingPage\":{\"logoUrl\":\"javascript:alert(1)\"}}");

        assertEquals("", content(resource.get()).get("logoUrl"));
    }

    @Test
    void saveRejectsAJavascriptFooterLink() {
        tenantConfig("{}");

        Response response = resource.update(Map.of(
                "brandName", "Acme",
                "footerLinks", List.of(Map.of("label", "Privacy", "url", "javascript:alert(1)"))));

        assertEquals(422, response.getStatus());
    }

    @Test
    void saveAcceptsMailtoAndTelFooterLinks() {
        tenantConfig("{}");

        Response response = resource.update(Map.of(
                "brandName", "Acme",
                "footerLinks", List.of(
                        Map.of("label", "Email us", "url", "mailto:help@acme.example"),
                        Map.of("label", "Call us", "url", "tel:+911800123456"),
                        Map.of("label", "Privacy", "url", "/privacy"))));

        assertEquals(200, response.getStatus());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> links = (List<Map<String, Object>>) content(response).get("footerLinks");
        assertEquals(3, links.size());
    }

    @Test
    void saveRejectsAFooterLinkMissingItsUrl() {
        tenantConfig("{}");

        assertEquals(422, resource.update(Map.of(
                "brandName", "Acme",
                "footerLinks", List.of(Map.of("label", "Privacy", "url", "")))).getStatus());
    }

    // ---- extra sections ----------------------------------------------

    @Test
    @SuppressWarnings("unchecked")
    void anExtraSectionRowLeftCompletelyEmptyIsDroppedRatherThanRejected() {
        // "+ Add section" then Save without typing is a slip, not an error.
        tenantConfig("{}");
        List<Map<String, Object>> sections = new ArrayList<>();
        sections.add(Map.of("heading", "Accessibility", "body", "We aim for WCAG 2.1 AA."));
        sections.add(Map.of("heading", "", "body", ""));

        Response response = resource.update(Map.of("brandName", "Acme", "sections", sections));

        assertEquals(200, response.getStatus());
        List<Map<String, Object>> saved = (List<Map<String, Object>>) content(response).get("sections");
        assertEquals(1, saved.size());
        assertEquals("Accessibility", saved.get(0).get("heading"));
    }

    @Test
    void anExtraSectionWithBodyButNoHeadingIsRejected() {
        tenantConfig("{}");

        assertEquals(422, resource.update(Map.of(
                "brandName", "Acme",
                "sections", List.of(Map.of("heading", "", "body", "Orphaned copy")))).getStatus());
    }

    @Test
    void tooManyExtraSectionsAreRejected() {
        tenantConfig("{}");
        List<Map<String, Object>> sections = new ArrayList<>();
        for (int i = 0; i < 11; i++) {
            sections.add(Map.of("heading", "S" + i, "body", "b"));
        }

        assertEquals(422, resource.update(Map.of("brandName", "Acme", "sections", sections)).getStatus());
    }

    @Test
    void overlongCopyIsRejectedRatherThanTruncated() {
        tenantConfig("{}");

        assertEquals(422, resource.update(Map.of(
                "brandName", "x".repeat(201))).getStatus());
    }

    // ---- the public endpoint -----------------------------------------

    @Test
    void publicEndpointServesTheTenantsConfiguredContent() {
        PublicLandingPageResource publicResource = new PublicLandingPageResource();
        publicResource.db = db;
        publicResource.mapper = mapper;
        publicResource.tenantId = "t1";
        tenantConfig("{\"landingPage\":{\"brandName\":\"Acme Water Board\"}}");

        Response response = publicResource.get();

        assertEquals(200, response.getStatus());
        assertEquals("Acme Water Board", content(response).get("brandName"));
    }

    @Test
    void publicEndpointServesDefaultsWhenDbWriterIsDown() {
        // The front door renders complete copy even with the backend cold --
        // a 500 here would be a blank landing page for every citizen.
        PublicLandingPageResource publicResource = new PublicLandingPageResource();
        publicResource.db = db;
        publicResource.mapper = mapper;
        publicResource.tenantId = "t1";
        when(db.getTenant("t1")).thenThrow(new RuntimeException("connection refused"));

        Response response = publicResource.get();

        assertEquals(200, response.getStatus());
        assertEquals("UniServe", content(response).get("brandName"));
        assertNotEquals("", content(response).get("tagline"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void publicEndpointExposesOnlyLandingPageCopyNotTheRestOfTheConfig() {
        // config_json also holds routing rules and SLA targets. This endpoint is
        // unauthenticated; it must never grow into a config dump.
        PublicLandingPageResource publicResource = new PublicLandingPageResource();
        publicResource.db = db;
        publicResource.mapper = mapper;
        publicResource.tenantId = "t1";
        tenantConfig("{\"categories\":[\"outage\"],\"slaTargets\":{\"high\":4},"
                + "\"landingPage\":{\"brandName\":\"Acme\"}}");

        Map<String, Object> body = (Map<String, Object>) publicResource.get().getEntity();

        assertEquals(1, body.size());
        assertTrue(body.containsKey("content"));
        Map<String, Object> content = (Map<String, Object>) body.get("content");
        assertFalse(content.containsKey("categories"));
        assertFalse(content.containsKey("slaTargets"));
    }
}
