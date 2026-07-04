package com.uniserve.adapters.whatsapp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uniserve.adapters.ChannelMessageReceived;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Unit tests for the WhatsApp webhook parser (Feature 02b). */
class WhatsAppParserTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private static final String TEXT_PAYLOAD = """
            {
              "object": "whatsapp_business_account",
              "entry": [{
                "changes": [{
                  "value": {
                    "messages": [{
                      "from": "919876543210",
                      "id": "wamid.test001",
                      "timestamp": "1719475200",
                      "text": { "body": "My electricity bill is double this month" },
                      "type": "text"
                    }],
                    "contacts": [{ "profile": { "name": "Rajesh Kumar" } }]
                  }
                }]
              }]
            }
            """;

    @Test
    void parsesTextMessageToVerifiedPhoneIdentity() throws Exception {
        JsonNode root = mapper.readTree(TEXT_PAYLOAD);
        List<ChannelMessageReceived> events = WhatsAppParser.parse(root, "default");

        assertEquals(1, events.size());
        ChannelMessageReceived event = events.get(0);
        assertEquals("whatsapp", event.channel());
        assertEquals("phone", event.channelIdentity().type());
        assertEquals("+919876543210", event.channelIdentity().value());
        assertTrue(event.channelIdentity().verified(), "WhatsApp identity is always verified");
        assertEquals("My electricity bill is double this month", event.rawText());
        assertEquals(ChannelMessageReceived.TYPE, event.type());
    }

    @Test
    void extractsInteractiveButtonReplyTitleAsText() throws Exception {
        String payload = """
                {
                  "entry": [{ "changes": [{ "value": { "messages": [{
                    "from": "919812345678",
                    "id": "wamid.btn",
                    "timestamp": "1719475300",
                    "type": "interactive",
                    "interactive": { "type": "button_reply", "button_reply": { "id": "b1", "title": "Yes, proceed" } }
                  }]}}]}]
                }
                """;
        List<ChannelMessageReceived> events = WhatsAppParser.parse(mapper.readTree(payload), "default");
        assertEquals("Yes, proceed", events.get(0).rawText());
    }

    @Test
    void collectsMediaIdForImageMessage() throws Exception {
        String payload = """
                {
                  "entry": [{ "changes": [{ "value": { "messages": [{
                    "from": "919800000001",
                    "id": "wamid.img",
                    "timestamp": "1719475400",
                    "type": "image",
                    "image": { "id": "media-123", "mime_type": "image/jpeg" }
                  }]}}]}]
                }
                """;
        ChannelMessageReceived event = WhatsAppParser.parse(mapper.readTree(payload), "default").get(0);
        assertEquals(List.of("media-123"), event.rawMediaUrls());
    }

    @Test
    void normalisesPhoneToE164() {
        assertEquals("+919876543210", WhatsAppParser.toE164("919876543210"));
        assertEquals("+919876543210", WhatsAppParser.toE164("+919876543210"));
    }
}
