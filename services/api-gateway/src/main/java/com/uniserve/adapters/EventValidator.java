package com.uniserve.adapters;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates the shape of a {@link ChannelMessageReceived} against the adapter
 * contract (Feature 02f). Pure logic — no framework dependencies — so it can be
 * reused by the validation endpoint and exercised in unit tests.
 */
public final class EventValidator {

    private static final Set<String> ALLOWED_CHANNELS = Set.of("email", "whatsapp");
    private static final Set<String> ALLOWED_IDENTITY_TYPES =
            Set.of("phone", "email", "handle", "session", "unknown");

    private EventValidator() {
    }

    /** Return the list of validation errors; empty means the event is valid. */
    public static List<String> validate(ChannelMessageReceived event) {
        List<String> errors = new ArrayList<>();
        if (event == null) {
            errors.add("event body is missing");
            return errors;
        }

        if (!ChannelMessageReceived.TYPE.equals(event.type())) {
            errors.add("type must be '" + ChannelMessageReceived.TYPE + "'");
        }
        if (isBlank(event.channel())) {
            errors.add("channel is required");
        } else if (!ALLOWED_CHANNELS.contains(event.channel())) {
            errors.add("channel must be one of " + ALLOWED_CHANNELS);
        }

        ChannelIdentity identity = event.channelIdentity();
        if (identity == null) {
            errors.add("channelIdentity is required");
        } else if (isBlank(identity.type())) {
            errors.add("channelIdentity.type is required");
        } else if (!ALLOWED_IDENTITY_TYPES.contains(identity.type())) {
            errors.add("channelIdentity.type must be one of " + ALLOWED_IDENTITY_TYPES);
        }

        if (isBlank(event.rawText())) {
            errors.add("rawText is required");
        }
        if (isBlank(event.sentAt())) {
            errors.add("sentAt is required");
        }
        return errors;
    }

    public static boolean isValid(ChannelMessageReceived event) {
        return validate(event).isEmpty();
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
