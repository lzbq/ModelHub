package com.hmdp.gateway;

import com.hmdp.dto.Result;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static com.hmdp.gateway.GatewayTypes.*;

/**
 *1、额度预留和真实 usage 结算 调用流程大致是：
 i.根据输入大小和 max_tokens 估算需要预留的 token。
 ii.在同一个数据库事务里插入 tb_gateway_usage 调用流水，并增加 tb_token_account.reserved_quota。
 iii.调用上游模型。
 iv.上游成功后读取真实 usage.prompt_tokens / completion_tokens。
 v.用真实 token 结算：增加 used_quota，释放 reserved_quota，记录成本和响应。
 vi.如果明确失败，释放预留；如果结果不确定，保留预留并标记 NEEDS_RECONCILIATION 等待对账。
 * 2、调用记录和审计
 * tb_gateway_usage 记录请求 ID、用户、API Key、模型、状态、预留 token、真实 token、成本、上游 request id、错误码。
 * /gateway/usage 可以分页查当前用户最近调用记录。
 * */
@Service
public class GatewayLedger {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final GatewayProperties properties;
    private static final RowMapper<Entry> ENTRY = (rs, n) -> new Entry(
            rs.getString("request_id"), rs.getLong("user_id"), rs.getLong("model_id"), rs.getString("model"),
            rs.getString("fingerprint"), rs.getLong("reserved_tokens"), rs.getString("status"),
            rs.getString("response_json"), rs.getString("error_code"), rs.getLong("input_price"), rs.getLong("output_price"));

    public GatewayLedger(JdbcTemplate jdbc, PlatformTransactionManager manager, GatewayProperties properties) {
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager);
        this.properties = properties;
    }

    public Reservation reserve(Identity identity, String idempotencyKey, String fingerprint, Model model, long amount) {
        Entry existing = find(identity.principal(), idempotencyKey);
        if (existing != null) return duplicate(existing, fingerprint);
        String id = UUID.randomUUID().toString();
        try {
            return transaction.execute(tx -> {
                jdbc.update("""
                        INSERT INTO tb_gateway_usage
                        (request_id, user_id, api_key_id, principal, idempotency_key, fingerprint, model_id, model,
                         reserved_tokens, status, input_price, output_price, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """, id, identity.userId(), identity.keyId(), identity.principal(), idempotencyKey, fingerprint,
                        model.modelId(), model.alias(), amount, model.inputPrice(), model.outputPrice());
                int changed = jdbc.update("""
                        UPDATE tb_token_account SET reserved_quota = reserved_quota + ?, version = version + 1,
                          update_time = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND model_id = ? AND (expire_time IS NULL OR expire_time > CURRENT_TIMESTAMP)
                          AND total_quota >= used_quota + reserved_quota + ?
                        """, amount, identity.userId(), model.modelId(), amount);
                if (changed != 1) {
                    throw new GatewayException(402, "insufficient_quota", "该模型可用额度不足或已过期，请购买套餐后重试");
                }
                return new Reservation(new Entry(id, identity.userId(), model.modelId(), model.alias(), fingerprint,
                        amount, "PENDING", null, null, model.inputPrice(), model.outputPrice()), true);
            });
        } catch (DuplicateKeyException e) {
            Entry winner = find(identity.principal(), idempotencyKey);
            if (winner == null) throw e;
            return duplicate(winner, fingerprint);
        }
    }

    private Reservation duplicate(Entry entry, String fingerprint) {
        if (!entry.fingerprint().equals(fingerprint)) {
            throw new GatewayException(409, "idempotency_conflict", "同一个 Idempotency-Key 不能用于不同的请求内容");
        }
        return new Reservation(entry, false);
    }

    public Entry find(String principal, String key) {
        List<Entry> list = jdbc.query("SELECT * FROM tb_gateway_usage WHERE principal = ? AND idempotency_key = ?", ENTRY, principal, key);
        return list.isEmpty() ? null : list.getFirst();
    }

    private Entry lock(String requestId) {
        return jdbc.queryForObject("SELECT * FROM tb_gateway_usage WHERE request_id = ? FOR UPDATE", ENTRY, requestId);
    }

    public boolean settle(String requestId, Usage usage, String responseJson) {
        return Boolean.TRUE.equals(transaction.execute(tx -> {
            Entry entry = lock(requestId);
            if ("SUCCEEDED".equals(entry.status())) return true;
            if ("FAILED".equals(entry.status())) return false;
            // Never release first: used and reserved change atomically, preserving other requests' reservations.
            int changed = jdbc.update("""
                    UPDATE tb_token_account SET used_quota = used_quota + ?, reserved_quota = reserved_quota - ?,
                      version = version + 1, update_time = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND model_id = ? AND reserved_quota >= ?
                      AND total_quota >= used_quota + reserved_quota - ? + ?
                    """, usage.totalTokens(), entry.reservedTokens(), entry.userId(), entry.modelId(),
                    entry.reservedTokens(), entry.reservedTokens(), usage.totalTokens());
            String status = changed == 1 ? "SUCCEEDED" : "NEEDS_RECONCILIATION";
            jdbc.update("""
                    UPDATE tb_gateway_usage SET status = ?, prompt_tokens = ?, completion_tokens = ?, total_tokens = ?,
                      cost_yuan = ?, response_json = ?, error_code = ?, updated_at = CURRENT_TIMESTAMP WHERE request_id = ?
                    """, status, usage.promptTokens(), usage.completionTokens(), usage.totalTokens(),
                    usage.costYuan(entry.inputPrice(), entry.outputPrice()), responseJson,
                    changed == 1 ? null : "settlement_quota_conflict", requestId);
            return changed == 1;
        }));
    }

    public void release(String requestId, String errorCode) {
        transaction.executeWithoutResult(tx -> {
            Entry entry = lock(requestId);
            if (!"PENDING".equals(entry.status())) return;
            int changed = jdbc.update("""
                    UPDATE tb_token_account SET reserved_quota = reserved_quota - ?, version = version + 1,
                      update_time = CURRENT_TIMESTAMP WHERE user_id = ? AND model_id = ? AND reserved_quota >= ?
                    """, entry.reservedTokens(), entry.userId(), entry.modelId(), entry.reservedTokens());
            if (changed != 1) throw new IllegalStateException("Gateway reservation invariant violated");
            jdbc.update("UPDATE tb_gateway_usage SET status = 'FAILED', error_code = ?, updated_at = CURRENT_TIMESTAMP WHERE request_id = ?",
                    errorCode, requestId);
        });
    }

    public void uncertain(String requestId, String errorCode) {
        jdbc.update("""
                UPDATE tb_gateway_usage SET status = 'NEEDS_RECONCILIATION', error_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE request_id = ? AND status = 'PENDING'
                """, errorCode, requestId);
    }

    /** A process crash cannot establish whether the provider billed; retain the reservation for reconciliation. */
    @Scheduled(fixedDelay = 60000)
    public void markInterruptedRequests() {
        // When disabled, allow existing installations to start before the opt-in migration is applied.
        if (!properties.isEnabled()) return;
        jdbc.update("""
                UPDATE tb_gateway_usage SET status = 'NEEDS_RECONCILIATION', error_code = 'interrupted_request',
                  updated_at = CURRENT_TIMESTAMP WHERE status = 'PENDING' AND created_at < ?
                """, Timestamp.valueOf(LocalDateTime.now().minusSeconds(Math.max(10, properties.getTimeoutSeconds()) + 120L)));
    }

    public Result usage(long userId, int current) {
        int page = Math.max(1, Math.min(current, 1000000));
        List<Map<String, Object>> records = jdbc.query("SELECT * FROM tb_gateway_usage WHERE user_id = ? ORDER BY created_at DESC, request_id DESC LIMIT 10 OFFSET ?",
                (rs, n) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("requestId", rs.getString("request_id"));
                    row.put("modelId", rs.getLong("model_id"));
                    row.put("model", rs.getString("model"));
                    row.put("status", rs.getString("status"));
                    row.put("promptTokens", rs.getObject("prompt_tokens"));
                    row.put("completionTokens", rs.getObject("completion_tokens"));
                    row.put("totalTokens", rs.getObject("total_tokens"));
                    row.put("reservedTokens", rs.getLong("reserved_tokens"));
                    row.put("costYuan", rs.getBigDecimal("cost_yuan"));
                    row.put("createdAt", rs.getObject("created_at", LocalDateTime.class));
                    row.put("errorCode", rs.getString("error_code"));
                    row.put("providerRequestId", rs.getString("provider_request_id"));
                    return row;
                }, userId, (page - 1) * 10);
        Long total = jdbc.queryForObject("SELECT COUNT(*) FROM tb_gateway_usage WHERE user_id = ?", Long.class, userId);
        return Result.ok(records, total);
    }

    public void providerRequestId(String requestId, String providerId) {
        if (providerId != null && !providerId.isBlank()) {
            jdbc.update("UPDATE tb_gateway_usage SET provider_request_id = ? WHERE request_id = ?",
                    providerId.substring(0, Math.min(200, providerId.length())), requestId);
        }
    }
}
