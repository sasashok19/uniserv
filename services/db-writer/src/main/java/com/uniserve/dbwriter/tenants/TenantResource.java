package com.uniserve.dbwriter.tenants;

import com.uniserve.dbwriter.common.ApiException;
import com.uniserve.dbwriter.model.Tenant;
import io.quarkus.hibernate.orm.panache.Panache;
import jakarta.transaction.Transactional;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.PUT;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.util.Map;

/** Tenant data API (Feature 04/11): {@code /api/v1/db/tenants}. */
@Path("/api/v1/db/tenants")
@Produces(MediaType.APPLICATION_JSON)
public class TenantResource {

    @GET
    @Path("/{id}")
    public Map<String, Object> get(@PathParam("id") String id) {
        Tenant t = Tenant.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "tenant not found: " + id);
        }
        return t.toMap();
    }

    @PUT
    @Path("/{id}/config")
    @Consumes(MediaType.APPLICATION_JSON)
    @Transactional
    public Map<String, Object> updateConfig(@PathParam("id") String id, Map<String, Object> body) {
        Tenant t = Tenant.findById(id);
        if (t == null) {
            throw new ApiException(404, "NOT_FOUND", "tenant not found: " + id);
        }
        Object configJson = body.get("configJson");
        if (configJson == null) {
            throw new ApiException(400, "CONFIG_REQUIRED", "configJson is required");
        }
        t.configJson = String.valueOf(configJson);
        Panache.getEntityManager().flush();
        return t.toMap();
    }
}
