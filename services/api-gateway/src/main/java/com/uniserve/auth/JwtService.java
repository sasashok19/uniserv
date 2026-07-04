package com.uniserve.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.interfaces.DecodedJWT;
import jakarta.annotation.PostConstruct;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;

/** Issues and verifies HS256 JWTs for agent auth (Feature 11). */
@ApplicationScoped
public class JwtService {

    private static final String ISSUER = "https://uniserve.local";

    @ConfigProperty(name = "jwt.secret")
    String secret;

    @ConfigProperty(name = "jwt.expiry.access", defaultValue = "15m")
    String accessExpiry;

    @ConfigProperty(name = "jwt.expiry.refresh", defaultValue = "7d")
    String refreshExpiry;

    private Algorithm algorithm;

    @PostConstruct
    void init() {
        algorithm = Algorithm.HMAC256(secret);
    }

    public String createAccessToken(Map<String, Object> agent) {
        Instant now = Instant.now();
        return JWT.create()
                .withIssuer(ISSUER)
                .withSubject(str(agent, "id"))
                .withClaim("tenant_id", str(agent, "tenant_id"))
                .withClaim("role", str(agent, "role"))
                .withClaim("name", str(agent, "name"))
                .withClaim("email", str(agent, "email"))
                .withIssuedAt(now)
                .withExpiresAt(now.plus(parse(accessExpiry)))
                .sign(algorithm);
    }

    public String createRefreshToken(String agentId, String jti) {
        Instant now = Instant.now();
        return JWT.create()
                .withIssuer(ISSUER)
                .withSubject(agentId)
                .withJWTId(jti)
                .withClaim("type", "refresh")
                .withIssuedAt(now)
                .withExpiresAt(now.plus(parse(refreshExpiry)))
                .sign(algorithm);
    }

    /** Dev-only helper to mint an already-expired access token (for testing 401). */
    public String createExpiredToken(Map<String, Object> agent) {
        Instant past = Instant.now().minus(Duration.ofMinutes(30));
        return JWT.create()
                .withIssuer(ISSUER)
                .withSubject(str(agent, "id"))
                .withClaim("role", str(agent, "role"))
                .withClaim("tenant_id", str(agent, "tenant_id"))
                .withIssuedAt(past)
                .withExpiresAt(past.plus(Duration.ofMinutes(1)))
                .sign(algorithm);
    }

    public DecodedJWT verify(String token) {
        return JWT.require(algorithm).withIssuer(ISSUER).build().verify(token);
    }

    public long accessExpirySeconds() {
        return parse(accessExpiry).toSeconds();
    }

    private static Duration parse(String spec) {
        String s = spec.trim().toLowerCase();
        char unit = s.charAt(s.length() - 1);
        long value = Long.parseLong(s.substring(0, s.length() - 1));
        return switch (unit) {
            case 's' -> Duration.ofSeconds(value);
            case 'm' -> Duration.ofMinutes(value);
            case 'h' -> Duration.ofHours(value);
            case 'd' -> Duration.ofDays(value);
            default -> Duration.ofSeconds(Long.parseLong(s));
        };
    }

    private static String str(Map<String, Object> m, String k) {
        Object v = m.get(k);
        return v == null ? null : String.valueOf(v);
    }
}
