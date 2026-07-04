package com.uniserve.auth;

import jakarta.enterprise.context.RequestScoped;

/** Per-request authenticated agent, populated by {@link AuthFilter}. */
@RequestScoped
public class CurrentUser {

    private boolean authenticated;
    private String agentId;
    private String tenantId;
    private String role;
    private String name;
    private String email;

    public void set(String agentId, String tenantId, String role, String name, String email) {
        this.authenticated = true;
        this.agentId = agentId;
        this.tenantId = tenantId;
        this.role = role;
        this.name = name;
        this.email = email;
    }

    public boolean isAuthenticated() {
        return authenticated;
    }

    public String agentId() {
        return agentId;
    }

    public String tenantId() {
        return tenantId;
    }

    public String role() {
        return role;
    }

    public String name() {
        return name;
    }

    public String email() {
        return email;
    }

    public boolean can(String action) {
        return RbacPolicy.can(role, action);
    }
}
