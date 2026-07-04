package com.uniserve.dbwriter.identity;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.db.Db;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Identity-profile CRUD + merge (Feature 04). Consumed by the ai-core identity
 * resolver (Feature 03); this service owns the SQLite writes.
 */
@ApplicationScoped
public class IdentityService {

    @Inject
    Db db;

    public Map<String, Object> create(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        if (tenantId == null) {
            throw new ApiException(400, "TENANT_REQUIRED", "tenantId is required");
        }
        String id = UUID.randomUUID().toString();
        String masterId = strOr(body, "masterId", UUID.randomUUID().toString());
        db.update("""
                INSERT INTO identity_profiles
                  (id, tenant_id, master_id, name, email, phone, channel_ids_json, is_anonymous, anon_ref_id)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                id, tenantId, masterId,
                str(body, "name"),
                str(body, "email"),
                str(body, "phone"),
                strOr(body, "channelIdsJson", "[]"),
                boolInt(body, "isAnonymous"),
                str(body, "anonRefId"));
        return getById(id).orElseThrow();
    }

    public Optional<Map<String, Object>> getById(String id) {
        return db.queryOne("SELECT * FROM identity_profiles WHERE id = ?", id);
    }

    public Optional<Map<String, Object>> findByEmail(String tenantId, String email) {
        return db.queryOne(
                "SELECT * FROM identity_profiles WHERE tenant_id = ? AND email = ? AND merged_into IS NULL",
                tenantId, email);
    }

    public Optional<Map<String, Object>> findByPhone(String tenantId, String phone) {
        return db.queryOne(
                "SELECT * FROM identity_profiles WHERE tenant_id = ? AND phone = ? AND merged_into IS NULL",
                tenantId, phone);
    }

    /** Anon refs are globally unique, so no tenant scope is needed (citizen portal). */
    public Optional<Map<String, Object>> findByAnonRef(String anonRefId) {
        return db.queryOne("SELECT * FROM identity_profiles WHERE anon_ref_id = ?", anonRefId);
    }

    public boolean anonRefExists(String tenantId, String anonRefId) {
        return db.queryOne(
                "SELECT id FROM identity_profiles WHERE tenant_id = ? AND anon_ref_id = ?",
                tenantId, anonRefId).isPresent();
    }

    /**
     * Merge the newer profile into the older/kept one: move its tickets, mark it
     * merged. Body: {@code keepMasterId}, {@code mergeMasterId}.
     */
    public Map<String, Object> merge(String keepId, Map<String, Object> body) {
        Map<String, Object> keep = getById(keepId)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "kept profile not found: " + keepId));
        String mergeMasterId = str(body, "mergeMasterId");
        if (mergeMasterId == null) {
            throw new ApiException(400, "MERGE_TARGET_REQUIRED", "mergeMasterId is required");
        }
        Map<String, Object> merged = db.queryOne(
                "SELECT * FROM identity_profiles WHERE master_id = ?", mergeMasterId)
                .orElseThrow(() -> new ApiException(404, "NOT_FOUND", "merge profile not found: " + mergeMasterId));

        String keepMasterId = String.valueOf(keep.get("master_id"));
        // Move tickets from merged profile to kept profile.
        db.update("UPDATE tickets SET identity_id = ? WHERE identity_id = ?",
                keep.get("id"), merged.get("id"));
        // Mark the newer profile as merged into the kept one.
        db.update("UPDATE identity_profiles SET merged_into = ?, updated_at = datetime('now') WHERE id = ?",
                keepMasterId, merged.get("id"));

        return Map.of("keptMasterId", keepMasterId, "mergedMasterId", mergeMasterId);
    }

    public List<Map<String, Object>> all(String tenantId) {
        return db.query("SELECT * FROM identity_profiles WHERE tenant_id = ?", tenantId);
    }

    /** Enqueue a pending-identity entry (email flow, Feature 03). */
    public Map<String, Object> enqueuePending(Map<String, Object> body) {
        String tenantId = str(body, "tenantId");
        String threadId = str(body, "threadId");
        String channel = str(body, "channel");
        if (tenantId == null || threadId == null || channel == null) {
            throw new ApiException(400, "PENDING_FIELDS_REQUIRED",
                    "tenantId, threadId and channel are required");
        }
        int hours = intOr(body, "timeoutHours", 48);
        String id = UUID.randomUUID().toString();
        db.update("""
                INSERT INTO identity_pending_queue
                  (id, tenant_id, thread_id, channel, channel_identity_value, raw_message, timeout_at)
                VALUES (?,?,?,?,?,?, datetime('now', ?))
                """,
                id, tenantId, threadId, channel,
                str(body, "channelIdentityValue"), str(body, "rawMessage"), "+" + hours + " hours");
        return db.queryOne("SELECT * FROM identity_pending_queue WHERE id = ?", id).orElseThrow();
    }

    /** Pending entries whose timeout has elapsed (Feature 03 timeout job). */
    public List<Map<String, Object>> timedOutPending(String tenantId) {
        return db.query(
                "SELECT * FROM identity_pending_queue WHERE tenant_id = ? AND timeout_at < datetime('now')",
                tenantId);
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
