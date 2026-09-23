package com.hmdp.gateway;

import com.hmdp.utils.UserHolder;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static com.hmdp.gateway.GatewayTypes.Identity;
/*
* 平台 API Key 管理
* 登录用户可以创建、查看、吊销自己的平台 Key。
* Key 明文只在创建时返回，数据库只保存 SHA-256 hash 和 prefix。
* /v1/** 不走普通登录拦截器，而是由网关自己验证 Bearer Key。
* */
@Service
public class GatewayKeyService {
    private final JdbcTemplate jdbc;
    private final SecureRandom random = new SecureRandom();

    public GatewayKeyService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Identity session() {
        if (UserHolder.getUser() == null) {
            throw new GatewayException(401, "authentication_required", "请先登录");
        }
        long id = UserHolder.getUser().getId();
        return new Identity(id, "session:" + id, null);
    }

    public Identity authenticate(String authorization) {
        String value = authorization == null ? "" : authorization.strip();
        if (value.length() > 100 || !value.regionMatches(true, 0, "Bearer ", 0, 7)) {
            throw new GatewayException(401, "invalid_api_key", "需要有效的平台 API Key");
        }
        String key = value.substring(7);
        if (!key.startsWith("mh_")) {
            throw new GatewayException(401, "invalid_api_key", "需要有效的平台 API Key");
        }
        List<Identity> found = jdbc.query("SELECT id, user_id FROM tb_gateway_api_key WHERE key_hash = ? AND revoked_at IS NULL",
                (rs, n) -> new Identity(rs.getLong("user_id"), "key:" + rs.getString("id"), rs.getString("id")), hash(key));
        if (found.isEmpty()) throw new GatewayException(401, "invalid_api_key", "平台 API Key 无效或已禁用");
        Identity identity = found.getFirst();
        jdbc.update("UPDATE tb_gateway_api_key SET last_used_at = CURRENT_TIMESTAMP WHERE id = ? AND revoked_at IS NULL", identity.keyId());
        return identity;
    }

    public Map<String, Object> create(long userId, String name) {
        if (name == null || name.isBlank() || name.strip().length() > 64) {
            throw new GatewayException(400, "invalid_name", "Key 名称需为 1 到 64 个字符");
        }
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String secret = "mh_" + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        String id = UUID.randomUUID().toString();
        String prefix = secret.substring(0, 11);
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("INSERT INTO tb_gateway_api_key (id, user_id, name, prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                id, userId, name.strip(), prefix, hash(secret), now);
        return Map.of("id", id, "name", name.strip(), "prefix", prefix, "key", secret, "createdAt", now);
    }

    public List<Map<String, Object>> list(long userId) {
        return jdbc.query("SELECT id, name, prefix, created_at, last_used_at, revoked_at FROM tb_gateway_api_key WHERE user_id = ? ORDER BY created_at DESC",
                (rs, n) -> {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("id", rs.getString("id"));
                    item.put("name", rs.getString("name"));
                    item.put("prefix", rs.getString("prefix"));
                    item.put("createdAt", rs.getObject("created_at", LocalDateTime.class));
                    item.put("lastUsedAt", rs.getObject("last_used_at", LocalDateTime.class));
                    item.put("revokedAt", rs.getObject("revoked_at", LocalDateTime.class));
                    item.put("status", rs.getTimestamp("revoked_at") == null ? 1 : 0);
                    return item;
                }, userId);
    }

    public void revoke(long userId, String id) {
        jdbc.update("UPDATE tb_gateway_api_key SET revoked_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND revoked_at IS NULL", id, userId);
    }

    public static String hash(String input) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable");
        }
    }
}
