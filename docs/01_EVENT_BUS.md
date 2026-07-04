# Feature 01 — Event Bus

## Phase Scope
- **Phase 1:** Full implementation
- **Phase 2:** No changes needed

## What This Module Does
Sets up Valkey Streams as the central async event bus. All inter-service
communication is event-driven. No service calls another service's business
logic directly.

## Boundaries
**Owns:** Valkey connection, stream creation, publisher/consumer base classes, DLQ.
**Does not own:** Business logic, message schemas (see 02f).

---

## Streams

| Stream | Producer | Consumer |
|---|---|---|
| `{tenant}:channel.message.received` | api-gateway | ai-core |
| `{tenant}:identity.resolved` | ai-core | ai-core, db-writer |
| `{tenant}:complaint.ready` | ai-core | ai-core |
| `{tenant}:ticket.created` | db-writer | dashboard, notifications |
| `{tenant}:ticket.updated` | db-writer | dashboard, notifications |
| `{tenant}:ai.reply.send` | ai-core | api-gateway (outbound) |
| `{tenant}:dlq` | any consumer on failure | manual review |

---

## Quarkus Implementation

```java
// services/api-gateway/src/main/java/com/uniserve/events/EventBusPublisher.java
@ApplicationScoped
public class EventBusPublisher {

    @Inject
    RedisDataSource redis;

    public String publish(String stream, BaseEvent event) {
        // Publish to Valkey stream
        // Returns message ID
    }
}

// BaseEvent record
public record BaseEvent(
    String id,          // UUID
    String tenantId,
    String type,        // e.g. "channel.message.received"
    String timestamp,   // ISO 8601
    String traceId,
    Map<String, Object> payload
) {}
```

## Python Consumer (ai-core)

```python
# services/ai-core/src/events/consumer.py
class BaseConsumer:
    async def consume(self, stream: str, group: str,
                      handler: Callable, batch_size: int = 10): ...
    async def ack(self, stream: str, message_id: str): ...
    # Auto-retries 3x, then sends to DLQ
```

---

## Environment Variables

```env
VALKEY_URL=redis://valkey:6379
EVENT_BUS_MAX_RETRIES=3
EVENT_BUS_RETRY_DELAY_MS=1000
EVENT_BUS_CONSUMER_GROUP=uniserve
```

---

## Test Stubs

```http
### Health check — Valkey connection
GET http://localhost:8080/api/v1/health/eventbus
Authorization: Bearer {{admin_token}}

### Expected response
HTTP/1.1 200 OK
{
  "status": "healthy",
  "valkey": "connected",
  "streams": ["channel.message.received", "ticket.created"]
}
```

---

## Mock Data Seed
No seed needed — event bus is infrastructure, not data.

---

## Testing

### Unit Tests
- Publisher writes to correct stream with correct shape
- Consumer ACKs message after successful handler
- Consumer sends to DLQ after 3 retries

### Integration Test
- Publish event → consumer receives within 500ms → ACK confirmed

---

## Phase 1 Implementation Notes (deviations & corrections)
- Health endpoint `/api/v1/health/eventbus` returns the **full 7-stream catalogue**; the doc's 2-item example is a representative subset.
- All event-bus endpoints are **unauthenticated** in Phase 1 (JWT arrives in 11_MULTI_TENANCY).
- Java unit tests run via a Maven container — the service image builds with `-DskipTests`.
