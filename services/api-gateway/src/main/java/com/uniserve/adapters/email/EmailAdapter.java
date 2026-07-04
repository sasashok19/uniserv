package com.uniserve.adapters.email;

import com.uniserve.adapters.ChannelIdentity;
import com.uniserve.adapters.ChannelMessagePublisher;
import com.uniserve.adapters.ChannelMessageReceived;
import io.quarkus.mailer.Mail;
import io.quarkus.mailer.Mailer;
import io.quarkus.scheduler.Scheduled;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.mail.Flags;
import jakarta.mail.Folder;
import jakarta.mail.Message;
import jakarta.mail.Multipart;
import jakarta.mail.Part;
import jakarta.mail.Session;
import jakarta.mail.Store;
import jakarta.mail.internet.InternetAddress;
import jakarta.mail.internet.MimeMessage;
import jakarta.mail.search.FlagTerm;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.time.Instant;
import java.util.Optional;
import java.util.Properties;
import java.util.UUID;

/**
 * Email channel adapter (Feature 02a): polls a mailbox over IMAP, normalises each
 * message to the canonical {@link ChannelMessageReceived} event, and sends
 * outbound replies over SMTP (via the Quarkus mailer, mocked in Phase 1 dev).
 *
 * <p>Identity is always {@code email / verified=false}, so the downstream identity
 * gate triggers. Parsing ({@link #parseMessage}) is pure and unit-tested; IMAP
 * connectivity is skipped when no host is configured.
 */
@ApplicationScoped
public class EmailAdapter {

    private static final Logger LOG = Logger.getLogger(EmailAdapter.class);

    @Inject
    ChannelMessagePublisher publisher;

    @Inject
    Mailer mailer;

    // Optional<String>: SmallRye treats an empty value as absent, so "unconfigured"
    // (dev default) becomes Optional.empty() instead of failing String conversion.
    @ConfigProperty(name = "email.imap.host")
    Optional<String> imapHost;

    @ConfigProperty(name = "email.imap.port", defaultValue = "993")
    int imapPort;

    @ConfigProperty(name = "email.imap.user")
    Optional<String> imapUser;

    @ConfigProperty(name = "email.imap.password")
    Optional<String> imapPassword;

    @ConfigProperty(name = "email.imap.mailbox", defaultValue = "INBOX")
    String mailbox;

    @ConfigProperty(name = "gateway.tenant-id", defaultValue = "default")
    String tenantId;

    /** Result of a poll cycle. */
    public record PollResult(int messagesProcessed, int errors) {
    }

    private boolean imapConfigured() {
        return imapHost.filter(h -> !h.isBlank()).isPresent();
    }

    @Scheduled(every = "{email.poll.interval}")
    void scheduledPoll() {
        if (!imapConfigured()) {
            return; // no mailbox configured (dev default) — nothing to poll
        }
        try {
            PollResult result = pollOnce();
            LOG.infof("Email poll: processed=%d errors=%d", result.messagesProcessed(), result.errors());
        } catch (Exception e) {
            LOG.errorf(e, "Scheduled email poll failed");
        }
    }

    /**
     * Poll the mailbox once for unseen messages. Returns 0/0 when IMAP is not
     * configured (dev) so the manual-poll endpoint stays usable without a server.
     */
    public PollResult pollOnce() {
        if (!imapConfigured()) {
            return new PollResult(0, 0);
        }

        int processed = 0;
        int errors = 0;
        Store store = null;
        Folder folder = null;
        try {
            Properties props = new Properties();
            props.put("mail.store.protocol", "imaps");
            Session session = Session.getInstance(props);
            store = session.getStore("imaps");
            store.connect(imapHost.get(), imapPort, imapUser.orElse(""), imapPassword.orElse(""));

            folder = store.getFolder(mailbox);
            folder.open(Folder.READ_WRITE);

            Message[] unseen = folder.search(new FlagTerm(new Flags(Flags.Flag.SEEN), false));
            for (Message message : unseen) {
                try {
                    publisher.publish(parseMessage(message, tenantId));
                    message.setFlag(Flags.Flag.SEEN, true);
                    processed++;
                } catch (Exception e) {
                    errors++;
                    LOG.errorf(e, "Failed to process email message");
                }
            }
        } catch (Exception e) {
            errors++;
            LOG.errorf(e, "IMAP poll failed for host %s", imapHost);
        } finally {
            closeQuietly(folder);
            closeQuietly(store);
        }
        return new PollResult(processed, errors);
    }

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

    // ---- parsing (pure, unit-tested) -------------------------------------

    static ChannelMessageReceived parseMessage(Message message, String tenantId) throws Exception {
        String from = extractFrom(message);
        String rawText = extractText(message);
        String threadId = extractThreadId(message);
        String nowIso = Instant.now().toString();
        String sentAt = message.getSentDate() != null
                ? message.getSentDate().toInstant().toString() : nowIso;

        return new ChannelMessageReceived(
                UUID.randomUUID().toString(),
                tenantId,
                ChannelMessageReceived.TYPE,
                nowIso,
                "email",
                new ChannelIdentity("email", from, false),
                rawText,
                java.util.List.of(),
                null,               // languageHint
                threadId,
                threadId,           // inReplyTo == parent message id
                sentAt,
                nowIso,
                UUID.randomUUID().toString());
    }

    static String extractFrom(Message message) throws Exception {
        if (message.getFrom() == null || message.getFrom().length == 0) {
            return null;
        }
        return ((InternetAddress) message.getFrom()[0]).getAddress();
    }

    /** In-Reply-To (or first References id), angle brackets stripped; null if none. */
    static String extractThreadId(Message message) throws Exception {
        String[] inReplyTo = message.getHeader("In-Reply-To");
        if (inReplyTo != null && inReplyTo.length > 0 && !isBlank(inReplyTo[0])) {
            return stripBrackets(inReplyTo[0].trim());
        }
        String[] references = message.getHeader("References");
        if (references != null && references.length > 0 && !isBlank(references[0])) {
            String[] ids = references[0].trim().split("\\s+");
            return stripBrackets(ids[ids.length - 1]);
        }
        return null;
    }

    static String extractText(Part part) throws Exception {
        Object content = part.getContent();
        if (part.isMimeType("text/plain")) {
            return ((String) content).trim();
        }
        if (part.isMimeType("text/html")) {
            return htmlToText((String) content);
        }
        if (content instanceof Multipart multipart) {
            String htmlFallback = null;
            for (int i = 0; i < multipart.getCount(); i++) {
                Part bodyPart = multipart.getBodyPart(i);
                if (bodyPart.isMimeType("text/plain")) {
                    return ((String) bodyPart.getContent()).trim();
                }
                if (bodyPart.isMimeType("text/html")) {
                    htmlFallback = htmlToText((String) bodyPart.getContent());
                } else if (bodyPart.getContent() instanceof Multipart) {
                    String nested = extractText(bodyPart);
                    if (nested != null && !nested.isBlank()) {
                        return nested;
                    }
                }
            }
            return htmlFallback;
        }
        return content == null ? null : content.toString().trim();
    }

    /** Minimal HTML → text: drop tags, unescape common entities, collapse whitespace. */
    static String htmlToText(String html) {
        if (html == null) {
            return null;
        }
        String text = html
                .replaceAll("(?is)<(script|style)[^>]*>.*?</\\1>", " ")
                .replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</p>", "\n")
                .replaceAll("<[^>]+>", "");
        text = text
                .replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"")
                .replace("&#39;", "'");
        return text.replaceAll("[ \\t]+", " ").replaceAll("\\n{2,}", "\n").trim();
    }

    private static String stripBrackets(String id) {
        return id.replaceAll("^<|>$", "");
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private void closeQuietly(Folder folder) {
        try {
            if (folder != null && folder.isOpen()) {
                folder.close(false);
            }
        } catch (Exception ignored) {
            // best effort
        }
    }

    private void closeQuietly(Store store) {
        try {
            if (store != null && store.isConnected()) {
                store.close();
            }
        } catch (Exception ignored) {
            // best effort
        }
    }
}
