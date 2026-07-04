package com.uniserve.dbwriter.db;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Thin JDBC helper over the Agroal {@link DataSource} (Feature 04). Plain SQL is
 * used deliberately for precise control over SQLite behaviour; rows are returned
 * as ordered maps so REST responses serialise directly to JSON.
 *
 * <p>The datasource pool is size 1 (see application.properties), so writes
 * serialise through the single connection — matching the "single writer" design.
 */
@ApplicationScoped
public class Db {

    @Inject
    DataSource dataSource;

    public List<Map<String, Object>> query(String sql, Object... params) {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            bind(ps, params);
            try (ResultSet rs = ps.executeQuery()) {
                return mapRows(rs);
            }
        } catch (SQLException e) {
            throw new DbException("Query failed: " + sql, e);
        }
    }

    public Optional<Map<String, Object>> queryOne(String sql, Object... params) {
        List<Map<String, Object>> rows = query(sql, params);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    public Object scalar(String sql, Object... params) {
        List<Map<String, Object>> rows = query(sql, params);
        if (rows.isEmpty()) {
            return null;
        }
        return rows.get(0).values().iterator().next();
    }

    public int update(String sql, Object... params) {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            bind(ps, params);
            return ps.executeUpdate();
        } catch (SQLException e) {
            throw new DbException("Update failed: " + sql, e);
        }
    }

    private void bind(PreparedStatement ps, Object... params) throws SQLException {
        for (int i = 0; i < params.length; i++) {
            ps.setObject(i + 1, params[i]);
        }
    }

    private List<Map<String, Object>> mapRows(ResultSet rs) throws SQLException {
        ResultSetMetaData meta = rs.getMetaData();
        int cols = meta.getColumnCount();
        List<Map<String, Object>> rows = new ArrayList<>();
        while (rs.next()) {
            Map<String, Object> row = new LinkedHashMap<>();
            for (int i = 1; i <= cols; i++) {
                row.put(meta.getColumnLabel(i), rs.getObject(i));
            }
            rows.add(row);
        }
        return rows;
    }

    /** Unchecked wrapper for SQL failures. */
    public static class DbException extends RuntimeException {
        public DbException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
