package com.uniserve.dbwriter.tickets;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import jakarta.enterprise.context.ApplicationScoped;

import java.time.Duration;
import java.util.Map;

/**
 * Short-TTL read cache for tickets (Feature 04). Serves hot reads from memory;
 * invalidated on every write. Key format: {@code ticket:{id}}.
 */
@ApplicationScoped
public class TicketCache {

    private final Cache<String, Map<String, Object>> cache = Caffeine.newBuilder()
            .maximumSize(1000)
            .expireAfterWrite(Duration.ofMinutes(2))
            .build();

    public Map<String, Object> getIfPresent(String ticketId) {
        return cache.getIfPresent(key(ticketId));
    }

    public void put(String ticketId, Map<String, Object> ticket) {
        cache.put(key(ticketId), ticket);
    }

    public void invalidate(String ticketId) {
        cache.invalidate(key(ticketId));
    }

    private String key(String ticketId) {
        return "ticket:" + ticketId;
    }
}
