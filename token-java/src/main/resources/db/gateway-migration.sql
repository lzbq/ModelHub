-- MySQL 8.x. Run after modelhub.sql, or against an existing ModelHub database.
-- Repeatable: existing accounts, orders and usage rows are preserved.
USE modelhub;
SET @gateway_has_reserved = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tb_token_account' AND COLUMN_NAME = 'reserved_quota');
SET @gateway_add_reserved = IF(@gateway_has_reserved = 0,
  'ALTER TABLE tb_token_account ADD COLUMN reserved_quota BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT ''网关待结算预留额度'' AFTER used_quota',
  'SELECT 1');
PREPARE gateway_migration FROM @gateway_add_reserved;
EXECUTE gateway_migration;
DEALLOCATE PREPARE gateway_migration;

CREATE TABLE IF NOT EXISTS tb_gateway_api_key (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(64) NOT NULL,
  prefix VARCHAR(16) NOT NULL,
  key_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL DEFAULT NULL,
  revoked_at TIMESTAMP NULL DEFAULT NULL,
  UNIQUE KEY uk_gateway_key_hash (key_hash),
  KEY idx_gateway_key_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- This is the gateway consumption ledger; purchase-grant records remain in tb_token_quota_record.
-- response_json stores the bounded successful answer for idempotent replay; restrict DB access and
-- establish retention before public deployment. Prompts and plaintext keys are never persisted here.
CREATE TABLE IF NOT EXISTS tb_gateway_usage (
  request_id VARCHAR(36) NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  api_key_id VARCHAR(36) DEFAULT NULL,
  principal VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  idempotency_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  fingerprint CHAR(64) NOT NULL,
  model_id BIGINT UNSIGNED NOT NULL,
  model VARCHAR(100) NOT NULL,
  reserved_tokens BIGINT UNSIGNED NOT NULL,
  status VARCHAR(32) NOT NULL,
  prompt_tokens BIGINT UNSIGNED DEFAULT NULL,
  completion_tokens BIGINT UNSIGNED DEFAULT NULL,
  total_tokens BIGINT UNSIGNED DEFAULT NULL,
  input_price BIGINT UNSIGNED NOT NULL DEFAULT 0,
  output_price BIGINT UNSIGNED NOT NULL DEFAULT 0,
  cost_yuan DECIMAL(20,8) DEFAULT NULL COMMENT '目录价格估算元，不扣人民币余额',
  response_json MEDIUMTEXT DEFAULT NULL,
  provider_request_id VARCHAR(200) DEFAULT NULL,
  error_code VARCHAR(80) DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_gateway_idempotency (principal, idempotency_key),
  KEY idx_gateway_usage_user_time (user_id, created_at),
  KEY idx_gateway_usage_reconcile (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
