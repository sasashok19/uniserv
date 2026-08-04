package com.uniserve.auth;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Feature 24: RBAC on the unrouted-message queue.
 *
 * The provider-message-id plumbing that the rest of the fix rests on is tested
 * in its own packages ({@code adapters.whatsapp.WhatsAppWamidTest},
 * {@code adapters.email.OutboundMessageIdTest}).
 */
class InboundRoutingSupportTest {

    @Test
    void theUnroutedQueueIsLeadAndAdminOnly() {
        // Resolving an entry files a citizen's words onto a ticket of the
        // agent's choosing, and the queue exposes messages from citizens whose
        // ticket is unknown — neither is an agent-scoped decision.
        for (String action : new String[]{"unrouted.view", "unrouted.manage"}) {
            assertTrue(RbacPolicy.can("admin", action), action);
            assertTrue(RbacPolicy.can("lead", action), action);
            assertFalse(RbacPolicy.can("agent", action), action);
        }
    }

    @Test
    void theUnroutedPathIsAuthenticated() {
        // Omitting it from AuthFilter.isProtected would leave CurrentUser
        // unpopulated and the lead/admin check reading a null role — a silent
        // auth bypass rather than a visible failure.
        assertTrue(new AuthFilter().isProtectedPath("api/v1/unrouted-messages"));
        assertTrue(new AuthFilter().isProtectedPath("api/v1/unrouted-messages/abc/attach"));
    }
}
