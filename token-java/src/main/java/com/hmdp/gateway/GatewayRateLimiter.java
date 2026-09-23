package com.hmdp.gateway;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.util.List;
/*
* 限流
按调用主体限流：session 用户或 API Key。
Redis 中用 INCR + EXPIRE 60s 做每分钟请求数限制。
默认 requests-per-minute: 20。
* */
@Component
public class GatewayRateLimiter {
    private static final DefaultRedisScript<Long> SCRIPT = new DefaultRedisScript<>(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", Long.class);
    private final StringRedisTemplate redis;
    private final GatewayProperties properties;

    public GatewayRateLimiter(StringRedisTemplate redis, GatewayProperties properties) {
        this.redis = redis;
        this.properties = properties;
    }

    public void check(String principal) {
        Long count;
        try {
            count = redis.execute(SCRIPT, List.of("gateway:rate:" + principal));
        } catch (RuntimeException e) {
            throw new GatewayException(503, "rate_limit_unavailable", "限流服务暂不可用，请稍后重试");
        }
        if (count == null) throw new GatewayException(503, "rate_limit_unavailable", "限流服务暂不可用");
        if (count > Math.max(1, properties.getRequestsPerMinute())) {
            throw new GatewayException(429, "rate_limit_exceeded", "请求过于频繁，请一分钟后重试");
        }
    }
}
