package com.uniserve.adapters.email;

import io.quarkus.mailer.Mail;
import io.quarkus.mailer.Mailer;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

/**
 * Email channel adapter (Feature 02a): sends outbound replies over SMTP (via
 * the Quarkus mailer, mocked in Phase 1 dev).
 *
 * <p>Inbound email is webhook-only (see {@link EmailWebhookResource}) — Make.com
 * watches the mailbox and POSTs the parsed message, so this adapter no longer
 * polls IMAP itself.
 */
@ApplicationScoped
public class EmailAdapter {

    private static final Logger LOG = Logger.getLogger(EmailAdapter.class);

    @Inject
    Mailer mailer;

    /** Send an outbound reply over SMTP. Returns true when no exception is thrown. */
    public boolean sendReply(String toAddress, String subject, String body, String inReplyToMessageId) {
        Mail mail = Mail.withText(toAddress, subject, body);
        if (!isBlank(inReplyToMessageId)) {
            mail.addHeader("In-Reply-To", inReplyToMessageId);
            mail.addHeader("References", inReplyToMessageId);
        }
        mailer.send(mail);
        LOG.infof("Email reply sent to=%s subject=%s", toAddress, subject);
        return true;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
