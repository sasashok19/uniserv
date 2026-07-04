package com.uniserve.dbwriter.common;

import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.ExceptionMapper;
import jakarta.ws.rs.ext.Provider;

import java.util.Map;

/** Renders {@link ApiException} as {@code {"error": {"code","message"}}}. */
@Provider
public class ApiExceptionMapper implements ExceptionMapper<ApiException> {

    @Override
    public Response toResponse(ApiException e) {
        return Response.status(e.status())
                .entity(Map.of("error", Map.of(
                        "code", e.code(),
                        "message", e.getMessage())))
                .build();
    }
}
