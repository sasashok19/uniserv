package com.uniserve.auth;

/** Role-based access control policy (Feature 11). */
public final class RbacPolicy {

    private RbacPolicy() {
    }

    /** Returns true if the given role may perform the action. */
    public static boolean can(String role, String action) {
        boolean adminOrLead = "admin".equals(role) || "lead".equals(role);
        return switch (action) {
            case "ticket.view.all" -> adminOrLead;
            case "ticket.view.own" -> true;
            case "ticket.edit" -> adminOrLead;
            case "ticket.note.add" -> true;
            case "ticket.priority.edit" -> adminOrLead;
            case "ticket.assignee.edit" -> adminOrLead;
            case "ticket.status.open_to_assigned" -> adminOrLead;
            case "ticket.status.assigned_to_inprogress" -> true;
            case "ticket.status.inprogress_to_resolved" -> true;
            case "ticket.status.resolved_to_closed" -> adminOrLead;
            case "ticket.status.closed_to_reopened" -> adminOrLead;
            case "ticket.resolution.generate" -> true;
            case "ticket.export" -> adminOrLead;
            case "admin.view", "admin.agents.manage", "admin.tenant.config", "admin.tickets.archive-stale" ->
                    "admin".equals(role);
            case "announcements.view" -> true;
            case "announcements.manage", "admin.system.reset" -> "admin".equals(role);
            case "analytics.view" -> true;
            case "analytics.view.all" -> adminOrLead;
            default -> false;
        };
    }
}
