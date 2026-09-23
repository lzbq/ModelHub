package com.hmdp.utils;

import cn.hutool.json.JSONUtil;
import jakarta.annotation.Resource;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executor;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * 通用缓存访问组件：
 * 1. 空值缓存防止不存在的 ID 反复穿透到数据库；
 * 2. TTL 随机抖动避免大量 Key 同时过期形成缓存雪崩；
 * 3. Redisson 互斥重建降低热点 Key 失效时的缓存击穿风险。
 */
@Component
public class CacheClient {

    private static final long LOCK_WAIT_SECONDS = 1L;
    private static final long LOCK_LEASE_SECONDS = 10L;

    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private RedissonClient redissonClient;
    @Resource(name = "cacheRefreshExecutor")
    private Executor cacheRefreshExecutor;//后台线程池，用于异步刷新缓存。

    private final Set<String> refreshingKeys = ConcurrentHashMap.newKeySet();

    public void setWithRandomTtl(String key, Object value, long ttl, long jitter, TimeUnit unit) {
        stringRedisTemplate.opsForValue().set(
                key,
                JSONUtil.toJsonStr(value),
                ttlWithJitter(ttl, jitter),
                unit);
    }

    public <R, ID> R queryWithPassThroughAndMutex(
            ID id,
            Class<R> type,
            String keyPrefix,
            String lockPrefix,
            long cacheTtl,
            long nullTtl,
            long jitter,
            TimeUnit unit,
            Function<ID, R> dbFallback) {

        String key = keyPrefix + id;
        //先查redis
        String json = stringRedisTemplate.opsForValue().get(key);
        //Redis 有正常 JSON，直接反序列化返回。
        if (StringUtils.hasText(json)) {
            return JSONUtil.toBean(json, type);
        }
        // Redis 中存在空字符串，表示数据库已经确认该 ID 不存在。
        if (json != null) {
            return null;
        }
        //Redis 没有 key，尝试拿 Redisson 分布式锁。
        RLock lock = redissonClient.getLock(lockPrefix + id);
        boolean locked;
        try {
            //Redis重建锁 等待 1 秒，租约 10 秒
            locked = lock.tryLock(LOCK_WAIT_SECONDS, LOCK_LEASE_SECONDS, TimeUnit.SECONDS);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("cache rebuild lock interrupted, key=" + key, ex);
        }
        //拿不到锁，就再查一次 Redis；还没有就直接查 DB，但不回写缓存。
        if (!locked) {
            // 等待锁期间其他线程通常已经完成回填；再检查一次，避免直接访问数据库。
            String retryJson = stringRedisTemplate.opsForValue().get(key);
            if (StringUtils.hasText(retryJson)) {
                return JSONUtil.toBean(retryJson, type);
            }
            if (retryJson != null) {
                return null;
            }
            // 锁持有时间超出等待窗口时保证查询可用，但不回填，避免覆盖锁持有者的新值。
            /*
            * 这意味着在锁持有者回源很慢或失败时，其他线程仍可能直接查 DB，只是不回写缓存。
            * 所以它不是严格意义上的“所有未拿锁线程都阻塞等待缓存重建完成”，而是带降级的互斥回源。
            * */
            return dbFallback.apply(id);
        }

        try {
            //拿到锁后做Double Check 就是为了确认缓存是否已经被别的线程重建好了，避免无意义回源。
            /*
            * 1.线程 A、B 同时发现 Redis 没有 key
            2.A 先拿到锁，B 等锁
            3.A 查 DB，并把结果写回 Redis
            4.A 释放锁
            5.B 拿到锁
            这时 B 如果不再查一次 Redis，就会重复查 DB、重复写缓存。
            */
            json = stringRedisTemplate.opsForValue().get(key);
            if (StringUtils.hasText(json)) {
                return JSONUtil.toBean(json, type);
            }
            if (json != null) {
                return null;
            }
            //仍然没有，就查数据库。
            R value = dbFallback.apply(id);
            //数据库查不到，写入 Redis 空字符串，防止缓存穿透。
            if (value == null) {
                stringRedisTemplate.opsForValue().set(
                        key,
                        "",
                        ttlWithJitter(nullTtl, Math.min(jitter, nullTtl)),
                        unit);
                return null;
            }
            //数据库查到，写入 Redis，并加随机 TTL 抖动。
            setWithRandomTtl(key, value, cacheTtl, jitter, unit);
            return value;
        } finally {
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }

    /**
     * 这个方法用于列表缓存，比如热门模型榜单。
     */
    public <R> List<R> queryListWithLogicalExpire(
            String key,
            String lockKey,
            Class<R> elementType,
            Duration logicalTtl,
            Duration logicalJitter,
            Duration physicalTtl,
            Supplier<List<R>> dbFallback) {
        //读取 Redis 里的列表包装对象。
        LogicalListValue<R> cached = readLogicalList(key, elementType);
        //如果 key 不存在，同步加锁重建缓存。
        if (cached == null) {
            return buildMissingList(
                    key,
                    lockKey,
                    elementType,
                    logicalTtl,
                    logicalJitter,
                    physicalTtl,
                    dbFallback);
        }
        //如果逻辑没过期，直接返回数据。
        if (cached.expireAt() > System.currentTimeMillis()) {
            return cached.data();
        }
        //后台线程异步刷新缓存
        triggerAsyncListRefresh(
                key,
                lockKey,
                elementType,
                logicalTtl,
                logicalJitter,
                physicalTtl,
                dbFallback);
        //如果逻辑已过期，先返回旧数据。
        return cached.data();
    }
    //热门榜缓存完全不存在时重建
    private <R> List<R> buildMissingList(
            String key,
            String lockKey,
            Class<R> elementType,
            Duration logicalTtl,
            Duration logicalJitter,
            Duration physicalTtl,
            Supplier<List<R>> dbFallback) {

        RLock lock = redissonClient.getLock(lockKey);
        boolean locked;
        try {
            locked = lock.tryLock(LOCK_WAIT_SECONDS, LOCK_LEASE_SECONDS, TimeUnit.SECONDS);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("hot list cache lock interrupted, key=" + key, ex);
        }
        //拿不到锁时，再读一次 Redis。
        if (!locked) {
            LogicalListValue<R> retry = readLogicalList(key, elementType);
            //如果别人已经写好了，就返回缓存。如果还没有，就直接查数据库返回，但不写缓存。
            return retry != null ? retry.data() : dbFallback.get();
        }
        //拿到锁的人负责查数据库并写 Redis。
        try {
            LogicalListValue<R> retry = readLogicalList(key, elementType);
            if (retry != null) {
                return retry.data();
            }
            List<R> fresh = dbFallback.get();
            setLogicalList(key, fresh, logicalTtl, logicalJitter, physicalTtl);
            return fresh;
        } finally {
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }
    //异步刷新逻辑过期缓存：当热门榜逻辑过期后，不阻塞当前请求，而是丢给线程池刷新。
    private <R> void triggerAsyncListRefresh(
            String key,
            String lockKey,
            Class<R> elementType,
            Duration logicalTtl,
            Duration logicalJitter,
            Duration physicalTtl,
            Supplier<List<R>> dbFallback) {
        //防止同一个 JVM 内重复刷新
        //refreshingKeys 是一个 JVM 内存里的 Set：同一个服务实例里，同一个 lockKey 同一时间只提交一个刷新任务。
        //比如 100 个请求同时发现热门榜过期了，第一个请求会把 lockKey 放进 refreshingKeys，然后提交后台刷新任务。不会重复提交 100 个后台任务。
        if (!refreshingKeys.add(lockKey)) {
            return;
        }
        try {
            //提交后台任务
            cacheRefreshExecutor.execute(() -> {
                RLock lock = redissonClient.getLock(lockKey);
                boolean locked = false;
                try {
                    //0：不等待，抢不到锁就立刻放弃。
                    locked = lock.tryLock(0, LOCK_LEASE_SECONDS, TimeUnit.SECONDS);
                    if (!locked) {
                        return;
                    }
                    // Double Check：抢到锁后再检查一次缓存
                    LogicalListValue<R> latest = readLogicalList(key, elementType);
                    if (latest != null && latest.expireAt() > System.currentTimeMillis()) {
                        return;
                    }
                    List<R> fresh = dbFallback.get();
                    setLogicalList(key, fresh, logicalTtl, logicalJitter, physicalTtl);
                } catch (InterruptedException ex) {
                    Thread.currentThread().interrupt();
                } finally {
                    if (locked && lock.isHeldByCurrentThread()) {
                        lock.unlock();
                    }
                    refreshingKeys.remove(lockKey);//删除本机 refreshingKeys 标记。
                }
            });
        } catch (RuntimeException ex) {
            //如果线程池拒绝任务，或者提交任务时直接抛异常，需要把刚才加进去的 refreshingKeys 清掉。
            //否则任务根本没跑，但本机却以为它在刷新。
            refreshingKeys.remove(lockKey);
            throw ex;
        }
    }

    private <R> LogicalListValue<R> readLogicalList(String key, Class<R> elementType) {
        String json = stringRedisTemplate.opsForValue().get(key);
        if (!StringUtils.hasText(json)) {
            return null;
        }
        try {
            cn.hutool.json.JSONObject object = JSONUtil.parseObj(json);
            Long expireAt = object.getLong("expireAt");
            //如果没有 expireAt 或没有 data，说明这个 Redis value 不是当前逻辑过期格式，直接删除。
            if (expireAt == null || object.getJSONArray("data") == null) {
                stringRedisTemplate.delete(key);
                return null;
            }
            return new LogicalListValue<>(
                    JSONUtil.toList(object.getJSONArray("data"), elementType),
                    expireAt);
        } catch (RuntimeException ex) {
            // Delete values written by the former plain-list cache format.
            stringRedisTemplate.delete(key);
            return null;
        }
    }
    //负责把“列表数据 + 逻辑过期时间”写进 Redis
    private void setLogicalList(
            String key,
            List<?> value,
            Duration logicalTtl,
            Duration logicalJitter,
            Duration physicalTtl) {

        long logicalMillis = positiveMillis(logicalTtl, "logical ttl");
        long jitterMillis = Math.max(0, logicalJitter.toMillis());
        long expireAt = System.currentTimeMillis()
                + logicalMillis
                + (jitterMillis == 0 ? 0 : ThreadLocalRandom.current().nextLong(jitterMillis + 1));

        Map<String, Object> wrapper = new HashMap<>();
        wrapper.put("data", value);
        wrapper.put("expireAt", expireAt);
        stringRedisTemplate.opsForValue().set(
                key,
                JSONUtil.toJsonStr(wrapper),
                positiveMillis(physicalTtl, "physical ttl"),
                TimeUnit.MILLISECONDS);
    }

    private long positiveMillis(Duration duration, String name) {
        long millis = duration.toMillis();
        if (millis <= 0) {
            throw new IllegalArgumentException(name + " must be positive");
        }
        return millis;
    }
    //把列表数据 data 和逻辑过期时间 expireAt 绑在一起返回
    private record LogicalListValue<R>(List<R> data, long expireAt) {
    }

    private long ttlWithJitter(long ttl, long jitter) {
        if (ttl <= 0) {
            throw new IllegalArgumentException("cache ttl must be positive");
        }
        if (jitter <= 0) {
            return ttl;
        }
        return ttl + ThreadLocalRandom.current().nextLong(jitter + 1);
    }
}
