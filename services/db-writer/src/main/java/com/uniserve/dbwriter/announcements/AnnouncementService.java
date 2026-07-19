package com.uniserve.dbwriter.announcements;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Announcement;
import com.uniserve.dbwriter.util.SqliteTime;
import io.quarkus.panache.common.Sort;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.transaction.Transactional;

import java.util.List;
import java.util.Map;

/**
 * Announcement CRUD (UI_REVAMP_v2 Feature C). "Active" means {@code is_active=1}
 * AND not past its optional {@code expires_at} — expiry is evaluated at read
 * time (no background sweep), so an expired announcement simply stops appearing
 * in active lists without a state change.
 */
@ApplicationScoped
public class AnnouncementService {

    public List<Map<String, Object>> list(String tenantId, boolean activeOnly) {
        String where = "tenantId = ?1";
        List<Announcement> rows;
        if (activeOnly) {
            rows = Announcement.<Announcement>find(
                    where + " and isActive = 1 and (expiresAt is null or expiresAt > ?2)",
                    Sort.by("createdAt", Sort.Direction.Descending),
                    tenantId, SqliteTime.now()).list();
        } else {
            rows = Announcement.<Announcement>find(
                    where, Sort.by("createdAt", Sort.Direction.Descending), tenantId).list();
        }
        return rows.stream().map(Announcement::toMap).toList();
    }

    @Transactional
    public Map<String, Object> create(Map<String, Object> body) {
        Announcement a = new Announcement();
        a.tenantId = requireStr(body, "tenantId");
        a.title = validTitle(requireStr(body, "title"));
        a.body = validBody(requireStr(body, "body"));
        a.createdBy = requireStr(body, "createdBy");
        a.expiresAt = str(body, "expiresAt");
        a.persist();
        return a.toMap();
    }

    @Transactional
    public Map<String, Object> update(String id, Map<String, Object> body) {
        Announcement a = Announcement.findById(id);
        if (a == null) {
            throw new ApiException(404, "NOT_FOUND", "announcement not found: " + id);
        }
        if (body.containsKey("title")) {
            a.title = validTitle(requireStr(body, "title"));
        }
        if (body.containsKey("body")) {
            a.body = validBody(requireStr(body, "body"));
        }
        if (body.containsKey("isActive")) {
            Object active = body.get("isActive");
            a.isActive = Boolean.TRUE.equals(active) || Integer.valueOf(1).equals(active) ? 1 : 0;
        }
        if (body.containsKey("expiresAt")) {
            a.expiresAt = str(body, "expiresAt");
        }
        return a.toMap();
    }

    @Transactional
    public void delete(String id, String tenantId) {
        Announcement a = Announcement.findById(id);
        if (a == null || (tenantId != null && !tenantId.equals(a.tenantId))) {
            throw new ApiException(404, "NOT_FOUND", "announcement not found: " + id);
        }
        a.delete();
    }

    // ---- helpers -----------------------------------------------------

    private static String validTitle(String title) {
        if (title.trim().length() < 3) {
            throw new ApiException(422, "INVALID_ANNOUNCEMENT", "title must be at least 3 characters");
        }
        return title.trim();
    }

    private static String validBody(String body) {
        if (body.trim().length() < 10) {
            throw new ApiException(422, "INVALID_ANNOUNCEMENT", "body must be at least 10 characters");
        }
        return body.trim();
    }

    private static String requireStr(Map<String, Object> body, String key) {
        String value = str(body, key);
        if (value == null || value.isBlank()) {
            throw new ApiException(400, "FIELD_REQUIRED", key + " is required");
        }
        return value;
    }

    private static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        return v == null ? null : String.valueOf(v);
    }
}
