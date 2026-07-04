package com.uniserve.auth;

import com.auth0.jwt.interfaces.DecodedJWT;
import io.quarkus.elytron.security.common.BcryptUtil;
import io.quarkus.redis.datasource.RedisDataSource;
import io.quarkus.redis.datasource.value.ValueCommands;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.CookieParam;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.NewCookie;
import jakarta.ws.rs.core.Response;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/** Auth endpoints (Feature 11): login / refresh / logout (+ dev helpers). */
@Path("/api/v1/auth")
@Produces(MediaType.APPLICATION_JSON)
public class AuthResource {

    @Inject
    DbWriterClient db;

    @Inject
    JwtService jwt;

    @Inject
    RedisDataSource redis;

    @ConfigProperty(name = "app.env", defaultValue = "development")
    String appEnv;

    @ConfigProperty(name = "jwt.expiry.refresh", defaultValue = "7d")
    String refreshExpiry;

    private ValueCommands<String, String> values() {
        return redis.value(String.class, String.class);
    }

    @POST
    @Path("/login")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response login(Map<String, Object> body) {
        String email = str(body, "email");
        String password = str(body, "password");
        if (email == null || password == null) {
            return error(400, "BAD_REQUEST", "email and password are required");
        }
        Optional<Map<String, Object>> agentOpt = db.findAgentByEmail(email);
        if (agentOpt.isEmpty()) {
            return error(401, "INVALID_CREDENTIALS", "Invalid email or password");
        }
        Map<String, Object> agent = agentOpt.get();
        String hash = str(agent, "password_hash");
        if (hash == null || !BcryptUtil.matches(password, hash)) {
            return error(401, "INVALID_CREDENTIALS", "Invalid email or password");
        }
        if (isFalse(agent.get("is_active"))) {
            return error(403, "ACCOUNT_INACTIVE", "Account is deactivated");
        }

        String access = jwt.createAccessToken(agent);
        String jti = UUID.randomUUID().toString();
        String refresh = jwt.createRefreshToken(str(agent, "id"), jti);
        storeRefresh(str(agent, "id"), jti);

        return Response.ok(Map.of(
                        "access_token", access,
                        "expires_in", jwt.accessExpirySeconds(),
                        "role", str(agent, "role")))
                .cookie(refreshCookie(refresh))
                .build();
    }

    @POST
    @Path("/refresh")
    public Response refresh(@CookieParam("refresh_token") String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            return error(401, "NO_REFRESH_TOKEN", "Refresh token missing");
        }
        DecodedJWT decoded;
        try {
            decoded = jwt.verify(refreshToken);
        } catch (Exception e) {
            return error(401, "INVALID_REFRESH_TOKEN", "Refresh token invalid or expired");
        }
        String agentId = decoded.getSubject();
        String jti = decoded.getId();
        if (!redis.key(String.class).exists(refreshKey(agentId, jti))) {
            return error(401, "REFRESH_REVOKED", "Refresh token has been used or revoked");
        }
        // Rotate: revoke old, issue new.
        redis.key(String.class).del(refreshKey(agentId, jti));

        Map<String, Object> agent = db.getAgentById(agentId)
                .orElse(Map.of("id", agentId, "role", "agent"));
        String access = jwt.createAccessToken(agent);
        String newJti = UUID.randomUUID().toString();
        String newRefresh = jwt.createRefreshToken(agentId, newJti);
        storeRefresh(agentId, newJti);

        return Response.ok(Map.of(
                        "access_token", access,
                        "expires_in", jwt.accessExpirySeconds()))
                .cookie(refreshCookie(newRefresh))
                .build();
    }

    @POST
    @Path("/logout")
    public Response logout(@CookieParam("refresh_token") String refreshToken) {
        if (refreshToken != null && !refreshToken.isBlank()) {
            try {
                DecodedJWT decoded = jwt.verify(refreshToken);
                redis.key(String.class).del(refreshKey(decoded.getSubject(), decoded.getId()));
            } catch (Exception ignored) {
                // already invalid — nothing to revoke
            }
        }
        return Response.ok(Map.of("status", "logged_out"))
                .cookie(expiredRefreshCookie())
                .build();
    }

    @POST
    @Path("/forgot-password")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response forgotPassword(Map<String, Object> body) {
        // PHASE_1: email delivery wired in 14_NOTIFICATIONS. Always 200 to avoid enumeration.
        return Response.ok(Map.of("status", "reset_email_sent_if_account_exists")).build();
    }

    @POST
    @Path("/reset-password")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response resetPassword(Map<String, Object> body) {
        return Response.ok(Map.of("status", "password_reset")).build();
    }

    /** Dev-only: mint an already-expired access token to exercise the 401 path. */
    @GET
    @Path("/_dev/expired-token")
    public Response devExpiredToken(@QueryParam("email") String email) {
        if (!"development".equals(appEnv)) {
            return error(404, "NOT_FOUND", "not available");
        }
        Map<String, Object> agent = db.findAgentByEmail(email).orElse(Map.of("id", "dev", "role", "agent"));
        return Response.ok(Map.of("access_token", jwt.createExpiredToken(agent))).build();
    }

    // ---- helpers ---------------------------------------------------------

    private void storeRefresh(String agentId, String jti) {
        values().setex(refreshKey(agentId, jti), parseSeconds(refreshExpiry), "1");
    }

    private String refreshKey(String agentId, String jti) {
        return "refresh:" + agentId + ":" + jti;
    }

    private NewCookie refreshCookie(String value) {
        return new NewCookie.Builder("refresh_token")
                .value(value)
                .path("/")
                .httpOnly(true)
                .maxAge((int) parseSeconds(refreshExpiry))
                .build();
    }

    private NewCookie expiredRefreshCookie() {
        return new NewCookie.Builder("refresh_token").value("").path("/").maxAge(0).build();
    }

    private static long parseSeconds(String spec) {
        String s = spec.trim().toLowerCase();
        char unit = s.charAt(s.length() - 1);
        long v = Long.parseLong(s.substring(0, s.length() - 1));
        return switch (unit) {
            case 's' -> v;
            case 'm' -> v * 60;
            case 'h' -> v * 3600;
            case 'd' -> v * 86400;
            default -> Long.parseLong(s);
        };
    }

    private Response error(int status, String code, String message) {
        return Response.status(status)
                .entity(Map.of("error", Map.of("code", code, "message", message)))
                .build();
    }

    private static boolean isFalse(Object v) {
        if (v instanceof Number n) {
            return n.intValue() == 0;
        }
        return Boolean.FALSE.equals(v);
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
