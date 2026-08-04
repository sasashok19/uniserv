package com.uniserve.adapters;

/**
 * The outcome of an outbound channel send (Feature 24).
 *
 * Adapters used to return a bare {@code boolean}, which threw away the one
 * thing inbound routing most needed: the id the provider assigned the message.
 * WhatsApp gives us `context.id` on a swipe-reply and email gives us
 * `In-Reply-To` — both name a message we sent — so without recording our own
 * outbound ids, the most reliable routing signal available was unusable and a
 * citizen's "Yes it is" had to be matched by heuristics instead.
 *
 * @param sent             true on a 2xx from the provider
 * @param channelMessageId the provider's id for the message (a WhatsApp wamid,
 *                         an email Message-ID), or null when the provider did
 *                         not give one back — callers must treat it as optional
 *                         and fall through to the other routing rungs.
 */
public record SendResult(boolean sent, String channelMessageId) {
}
