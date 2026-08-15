package com.uniserve.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.core.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link WhatsAppMenuResource} and the {@link WhatsAppMenuContent}
 * rules behind it (Feature 26).
 *
 * <p>The load-bearing behaviours, same as the landing page: an unset field must
 * read as its DEFAULT (a blank welcome would send the citizen an empty WhatsApp
 * message), and a save must preserve the rest of {@code config_json} (or
 * re-wording the menu silently destroys the tenant's categories and SLA targets).
 */
class WhatsAppMenuResourceTest {

    private DbWriterClient db;
    private ObjectMapper mapper;
    private WhatsAppMenuResource resource;
    private CurrentUser admin;

    @BeforeEach
    void setUp() {
        db = mock(DbWriterClient.class);
        mapper = new ObjectMapper();
        admin = new CurrentUser();
        admin.set("a-1", "t1", "admin", "Admin", "admin@example.com");
        resource = new WhatsAppMenuResource();
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

    private static Map<String, Object> validBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("companyName", "TNEB");
        body.put("menuPrompt", "Press 1 for status, 2 to register, 3 to end");
        body.put("ticketDetails", "Ticket {ticket} is {status}");
        body.put("ticketCreated", "Registered {ticket}");
        return body;
    }

    // ---- read --------------------------------------------------------

    @Test
    void getReturnsACompleteSendableMenuWhenTenantHasNoConfig() {
        tenantConfig(null);

        Response response = resource.get();

        assertEquals(200, response.getStatus());
        Map<String, Object> content = content(response);
        // Every text field must be non-blank: any blank one becomes an empty
        // WhatsApp message the citizen cannot act on.
        for (Map.Entry<String, Object> e : content.entrySet()) {
            if (e.getValue() instanceof String s) {
                assertFalse(s.isBlank(), e.getKey() + " must have a default");
            }
        }
        assertEquals(Boolean.TRUE, content.get("enabled"));
        assertEquals(WhatsAppMenuContent.DEFAULT_SESSION_TTL_HOURS, content.get("sessionTtlHours"));
    }

    @Test
    void companyNameFallsBackToTheLandingPageBrandName() {
        // A tenant that has already branded its public page must not have to
        // type its own name a second time to brand WhatsApp.
        tenantConfig("{\"landingPage\":{\"brandName\":\"TNEB\"}}");

        assertEquals("TNEB", content(resource.get()).get("companyName"));
    }

    @Test
    void anExplicitCompanyNameBeatsTheBrandName() {
        tenantConfig("{\"landingPage\":{\"brandName\":\"TNEB\"},"
                + "\"whatsappMenu\":{\"companyName\":\"TNEB Customer Care\"}}");

        assertEquals("TNEB Customer Care", content(resource.get()).get("companyName"));
    }

    @Test
    void companyNameFallsBackToTheProductNameWhenNothingIsBranded() {
        tenantConfig("{}");

        assertEquals("UniServe", content(resource.get()).get("companyName"));
    }

    @Test
    void theWelcomeCarriesTheCompanyPlaceholderSoItCanBeBranded() {
        tenantConfig(null);

        assertTrue(String.valueOf(content(resource.get()).get("welcome")).contains("{company}"),
                "the welcome must name the company, or Feature 26's whole point is lost");
    }

    @Test
    void storedContentLaysOverDefaultsFieldByField() {
        tenantConfig("{\"whatsappMenu\":{\"farewell\":\"Nandri, have a great day\"}}");

        Map<String, Object> content = content(resource.get());

        assertEquals("Nandri, have a great day", content.get("farewell"));
        // Everything else must still resolve.
        assertTrue(String.valueOf(content.get("menuPrompt")).contains("Press 1"));
        assertNotNull(content.get("askTicketId"));
    }

    @Test
    void getSurvivesUnparseableConfigJson() {
        tenantConfig("{not valid json");

        Response response = resource.get();

        assertEquals(200, response.getStatus());
        assertEquals("UniServe", content(response).get("companyName"));
    }

    @Test
    void anOutOfRangeTtlThatReachedTheDbDirectlyIsClampedOnRead() {
        // TenantConfigResource replaces the whole config_json blob, so a
        // whatsappMenu object can reach the database without passing normalise.
        // 72h would have the session outlive WhatsApp's 24h reply window.
        tenantConfig("{\"whatsappMenu\":{\"sessionTtlHours\":72}}");

        assertEquals(WhatsAppMenuContent.DEFAULT_SESSION_TTL_HOURS,
                content(resource.get()).get("sessionTtlHours"));
    }

    @Test
    void aNonNumericTtlThatReachedTheDbDirectlyIsClampedOnRead() {
        tenantConfig("{\"whatsappMenu\":{\"sessionTtlHours\":\"soon\"}}");

        assertEquals(WhatsAppMenuContent.DEFAULT_SESSION_TTL_HOURS,
                content(resource.get()).get("sessionTtlHours"));
    }

    @Test
    void disablingTheMenuIsReadBack() {
        tenantConfig("{\"whatsappMenu\":{\"enabled\":false}}");

        assertEquals(Boolean.FALSE, content(resource.get()).get("enabled"));
    }

    // ---- write -------------------------------------------------------

    @Test
    void savingPreservesEveryOtherConfigKey() {
        tenantConfig("{\"categories\":[\"billing\"],\"generalSettings\":{\"replyWindowDays\":14},"
                + "\"landingPage\":{\"brandName\":\"TNEB\"}}");

        Response response = resource.update(validBody());

        assertEquals(200, response.getStatus());
        ArgumentCaptor<String> saved = ArgumentCaptor.forClass(String.class);
        verify(db).updateTenantConfig(anyString(), saved.capture());
        String json = saved.getValue();
        assertTrue(json.contains("\"categories\""), "re-wording the menu must not drop categories");
        assertTrue(json.contains("\"replyWindowDays\""), "must not drop generalSettings");
        assertTrue(json.contains("\"brandName\""), "must not drop the landing page");
        assertTrue(json.contains("\"whatsappMenu\""));
    }

    @Test
    void updateEchoesTheResolvedViewSoBlanksShowTheirDefaults() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("farewell", "");   // cleared -> means "use the default"

        Map<String, Object> content = content(resource.update(body));

        assertEquals("Thanks for reaching out. Have a great time", content.get("farewell"));
        assertEquals("TNEB", content.get("companyName"));
    }

    @Test
    void aMenuPromptMissingAnOptionIsRejected() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("menuPrompt", "Press 1 for status, Press 2 to register");

        Response response = resource.update(body);

        assertEquals(422, response.getStatus());
        verify(db, never()).updateTenantConfig(anyString(), anyString());
    }

    @Test
    void aDetailsTemplateWithoutTheTicketPlaceholderIsRejected() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("ticketDetails", "Status: {status}");

        assertEquals(422, resource.update(body).getStatus());
    }

    @Test
    void aTtlBeyondWhatsAppsReplyWindowIsRejected() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("sessionTtlHours", 48);

        Response response = resource.update(body);

        assertEquals(422, response.getStatus());
        assertTrue(String.valueOf(response.getEntity()).contains("24"));
    }

    @Test
    void aNonNumericTtlIsRejectedRatherThanSilentlyDefaulted() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("sessionTtlHours", "half a day");

        assertEquals(422, resource.update(body).getStatus());
    }

    @Test
    void anOverlongFieldIsRejected() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("farewell", "x".repeat(5000));

        assertEquals(422, resource.update(body).getStatus());
    }

    @Test
    void aBlankMenuPromptIsAcceptedAndMeansUseTheDefault() {
        tenantConfig("{}");
        Map<String, Object> body = validBody();
        body.put("menuPrompt", "");

        Response response = resource.update(body);

        assertEquals(200, response.getStatus());
        assertTrue(String.valueOf(content(response).get("menuPrompt")).contains("Press 1"));
    }

    // ---- RBAC --------------------------------------------------------

    @Test
    void nonAdminsCannotReadOrWriteTheMenu() {
        for (String role : new String[]{"agent", "lead"}) {
            CurrentUser other = new CurrentUser();
            other.set("a-2", "t1", role, "Someone", "s@example.com");
            resource.user = other;

            assertEquals(403, resource.get().getStatus(), role + " must not read the menu");
            assertEquals(403, resource.update(validBody()).getStatus(), role + " must not write the menu");
        }
        verify(db, never()).updateTenantConfig(anyString(), anyString());
    }

    @Test
    void theMenuPathIsBehindTheAuthFilter() {
        // Omitting it would leave CurrentUser unpopulated and the admin check
        // reading a null role — the exact failure the AuthFilter javadoc warns about.
        assertTrue(new AuthFilter().isProtectedPath("api/v1/tenant/whatsapp-menu"));
    }
}
