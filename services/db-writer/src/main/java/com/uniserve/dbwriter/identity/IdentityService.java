package com.uniserve.dbwriter.identity;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.IdentityPendingQueue;
import com.uniserve.dbwriter.model.IdentityProfile;
import com.uniserve.dbwriter.model.Ticket;
import com.uniserve.dbwriter.util.SqliteTime;
import io.quarkus.hibernate.orm.panache.Panache;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.transaction.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Identity-profile CRUD + merge (Feature 04), backed by Hibernate ORM with
 * Panache. Consumed by the ai-core identity resolver (Feature 03); this
 * service owns the SQLite writes.
 */
@ApplicationScoped
public class IdentityService {

    @Transactional
    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        if (tenantId == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        IdentityProfile p = new IdentityProfile();
        p.id = UUID.randomUUID().toString();
        p.tenantId = tenantId;
        p.masterId = strOr(body, "masterId", UUID.randomUUID().toString());
        p.name = str(body, "name");
        p.email = str(body, "email");
        p.phone = str(body, "phone");
        p.channelIdsJson = strOr(body, "channelIdsJson", "[]");
        p.isAnonymous = boolInt(body, "isAnonymous");
        p.anonRefId = str(body, "anonRefId");
        p.persistAndFlush();
        return p.toMap();
    }

    /**
     * Look up by primary key first, falling back to {@code masterId}.
     *
     * <p>{@code ticket.identity_id} is populated inconsistently across this
     * codebase: {@code IdentityService.merge()} treats it as the profile's
     * primary key, while ai-core's identity resolver (Feature 03) always
     * writes its own generated {@code masterId} there instead. Accepting
     * either here means callers resolving a ticket's identity don't need to
     * know which convention produced that particular row.
     */
    public Optional<Map<String, Object>> getById(String id) {
        IdentityProfile p = IdentityProfile.findById(id);
        if (p != null) {
            return Optional.of(p.toMap());
        }
        return IdentityProfile.<IdentityProfile>find("masterId", id)
                .firstResultOptional().map(IdentityProfile::toMap);
    }

    public Optional<Map<String, Object>> findByEmail(String tenantId, String email) {
        return IdentityProfile.<IdentityProfile>find(
                        "tenantId = ?1 and email = ?2 and mergedInto is null", tenantId, email)
                .firstResultOptional().map(IdentityProfile::toMap);
    }

    public Optional<Map<String, Object>> findByPhone(String tenantId, String phone) {
        return IdentityProfile.<IdentityProfile>find(
                        "tenantId = ?1 and phone = ?2 and mergedInto is null", tenantId, phone)
                .firstResultOptional().map(IdentityProfile::toMap);
    }

    /** Anon refs are globally unique, so no tenant scope is needed (citizen portal). */
    public Optional<Map<String, Object>> findByAnonRef(String anonRefId) {
        return IdentityProfile.<IdentityProfile>find("anonRefId", anonRefId)
                .firstResultOptional().map(IdentityProfile::toMap);
    }

    public boolean anonRefExists(String tenantId, String anonRefId) {
        return IdentityProfile.count("tenantId = ?1 and anonRefId = ?2", tenantId, anonRefId) > 0;
    }

    /**
     * Merge the newer profile into the older/kept one: move its tickets, mark it
     * merged. Body: {@code mergeMasterId}.
     */
    @Transactional
    public Map<String, Object> merge(String keepId, Map<String, Object> body) {
        IdentityProfile keep = IdentityProfile.findById(keepId);
        if (keep == null) {
            throw new ApiException(404, "NOT_FOUND", "kept profile not found: " + keepId);
        }
        String mergeMasterId = str(body, "mergeMasterId");
        if (mergeMasterId == null) {
            throw new ApiException(400, "MERGE_TARGET_REQUIRED", "mergeMasterId is required");
        }
        IdentityProfile merged = IdentityProfile.<IdentityProfile>find("masterId", mergeMasterId)
                .firstResultOptional()
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "merge profile not found: " + mergeMasterId));

        // Move tickets from merged profile to kept profile.
        Ticket.update("identityId = ?1 where identityId = ?2", keep.id, merged.id);
        // Mark the newer profile as merged into the kept one.
        merged.mergedInto = keep.masterId;
        Panache.getEntityManager().flush();

        return Map.of("keptMasterId", keep.masterId, "mergedMasterId", mergeMasterId);
    }

    /**
     * Enrich an existing profile with a newly-learned field (Feature 03/06):
     * e.g. a citizen who first emailed in later provides a mobile number, or
     * vice versa — same person, same record, just more known about them now.
     * Accepts {@code name}/{@code email}/{@code phone}; only overwrites a
     * field when it's currently blank, so a later channel never clobbers an
     * already-confirmed value.
     */
    @Transactional
    public Map<String, Object> update(String id, Map<String, Object> body) {
        IdentityProfile p = IdentityProfile.findById(id);
        if (p == null) {
            throw new ApiException(404, "NOT_FOUND", "identity not found: " + id);
        }
        String name = str(body, "name");
        String email = str(body, "email");
        String phone = str(body, "phone");
        if (name != null && (p.name == null || p.name.isBlank())) {
            p.name = name;
        }
        if (email != null && (p.email == null || p.email.isBlank())) {
            p.email = email;
        }
        if (phone != null && (p.phone == null || p.phone.isBlank())) {
            p.phone = phone;
        }
        Panache.getEntityManager().flush();
        return p.toMap();
    }

    public List<Map<String, Object>> all(String tenantId) {
        return IdentityProfile.<IdentityProfile>find("tenantId", tenantId)
                .list().stream().map(IdentityProfile::toMap).toList();
    }

    /** Typeahead for the analytics "by customer" filter (Feature 15) — partial match on name/email/phone. */
    public List<Map<String, Object>> search(String tenantId, String q) {
        String like = "%" + q + "%";
        return IdentityProfile.<IdentityProfile>find(
                        "tenantId = ?1 and mergedInto is null and "
                                + "(name like ?2 or email like ?2 or phone like ?2)",
                        tenantId, like)
                .page(0, 10).list().stream().map(IdentityProfile::toMap).toList();
    }

    /** Enqueue a pending-identity entry (email flow, Feature 03). */
    @Transactional
    public Map<String, Object> enqueuePending(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        String threadId = str(body, "threadId");
        String channel = str(body, "channel");
        if (tenantId == null || threadId == null || channel == null) {
            throw new ApiException(400, "PENDING_FIELDS_REQUIRED",
                    "tenantId, threadId and channel are required");
        }
        int hours = intOr(body, "timeoutHours", 48);

        IdentityPendingQueue q = new IdentityPendingQueue();
        q.id = UUID.randomUUID().toString();
        q.tenantId = tenantId;
        q.threadId = threadId;
        q.channel = channel;
        q.channelIdentityValue = str(body, "channelIdentityValue");
        q.rawMessage = str(body, "rawMessage");
        q.timeoutAt = SqliteTime.plusHours(hours);
        q.persistAndFlush();
        return q.toMap();
    }

    /** Pending entries whose timeout has elapsed (Feature 03 timeout job). */
    public List<Map<String, Object>> timedOutPending(String tenantId) {
        String now = SqliteTime.now();
        return IdentityPendingQueue.<IdentityPendingQueue>find(
                        "tenantId = ?1 and timeoutAt < ?2", tenantId, now)
                .list().stream().map(IdentityPendingQueue::toMap).toList();
    }

    private static int intOr(Map<String, Object> body, String key, int fallback) {
        Object v = body.get(key);
        return v == null ? fallback : ((Number) v).intValue();
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static String strOr(Map<String, Object> body, String key, String fallback) {
        String v = str(body, key);
        return v == null ? fallback : v;
    }

    private static int boolInt(Map<String, Object> body, String key) {
        Object v = body.get(key);
        if (v instanceof Boolean b) {
            return b ? 1 : 0;
        }
        if (v instanceof Number n) {
            return n.intValue();
        }
        return 0;
    }
}
