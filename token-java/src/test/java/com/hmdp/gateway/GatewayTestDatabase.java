package com.hmdp.gateway;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.util.UUID;

final class GatewayTestDatabase {
    final JdbcTemplate jdbc;
    final DataSourceTransactionManager manager;

    GatewayTestDatabase() {
        DriverManagerDataSource data = new DriverManagerDataSource();
        data.setDriverClassName("org.h2.Driver");
        data.setUrl("jdbc:h2:mem:gateway_" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000");
        data.setUsername("sa");
        data.setPassword("");
        jdbc = new JdbcTemplate(data);
        manager = new DataSourceTransactionManager(data);
        jdbc.execute("""
                CREATE TABLE tb_token_account(id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT, model_id BIGINT,
                  total_quota BIGINT NOT NULL, used_quota BIGINT NOT NULL DEFAULT 0, reserved_quota BIGINT NOT NULL DEFAULT 0,
                  expire_time TIMESTAMP, version INT NOT NULL DEFAULT 0, update_time TIMESTAMP,
                  UNIQUE(user_id, model_id))
                """);
        jdbc.execute("""
                CREATE TABLE tb_gateway_usage(request_id VARCHAR(36) PRIMARY KEY, user_id BIGINT, api_key_id VARCHAR(36),
                  principal VARCHAR(64), idempotency_key VARCHAR(100), fingerprint CHAR(64), model_id BIGINT, model VARCHAR(100),
                  reserved_tokens BIGINT, status VARCHAR(32), prompt_tokens BIGINT, completion_tokens BIGINT, total_tokens BIGINT,
                  input_price BIGINT, output_price BIGINT, cost_yuan DECIMAL(20,8), response_json CLOB,
                  provider_request_id VARCHAR(200), error_code VARCHAR(80), created_at TIMESTAMP, updated_at TIMESTAMP,
                  UNIQUE(principal, idempotency_key))
                """);
        jdbc.execute("""
                CREATE TABLE tb_gateway_api_key(id VARCHAR(36) PRIMARY KEY, user_id BIGINT, name VARCHAR(64), prefix VARCHAR(16),
                  key_hash CHAR(64) UNIQUE, created_at TIMESTAMP, last_used_at TIMESTAMP, revoked_at TIMESTAMP)
                """);
        jdbc.execute("""
                CREATE TABLE tb_ai_model(id BIGINT PRIMARY KEY, name VARCHAR(128), provider VARCHAR(64), category VARCHAR(32),
                  status INT, input_price BIGINT, output_price BIGINT, context_window INT)
                """);
        jdbc.update("INSERT INTO tb_ai_model VALUES (1, 'Test model', 'Test provider', 'chat', 1, 100, 400, 128000)");
        jdbc.update("INSERT INTO tb_token_account(user_id, model_id, total_quota) VALUES(10, 1, 10000)");
    }

    long value(String column) { return jdbc.queryForObject("SELECT " + column + " FROM tb_token_account WHERE user_id=10 AND model_id=1", Long.class); }
}
