package com.hmdp.utils;

import cn.hutool.json.JSONUtil;
import com.hmdp.entity.AiModel;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CacheClientTest {

    private static final String KEY = "cache:ai-model:99";
    private static final String LOCK_KEY = "lock:cache:ai-model:99";

    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;
    @Mock
    private RedissonClient redissonClient;
    @Mock
    private RLock lock;

    private CacheClient cacheClient;

    @BeforeEach
    void setUp() {
        cacheClient = new CacheClient();
        ReflectionTestUtils.setField(cacheClient, "stringRedisTemplate", stringRedisTemplate);
        ReflectionTestUtils.setField(cacheClient, "redissonClient", redissonClient);
        ReflectionTestUtils.setField(cacheClient, "cacheRefreshExecutor", (java.util.concurrent.Executor) Runnable::run);
        when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
    }

    @Test
    void shouldReturnNullMarkerWithoutQueryingDatabase() {
        when(valueOperations.get(KEY)).thenReturn("");
        AtomicBoolean databaseCalled = new AtomicBoolean(false);

        AiModel result = query(id -> {
            databaseCalled.set(true);
            return new AiModel().setId(id);
        });

        assertThat(result).isNull();
        assertThat(databaseCalled).isFalse();
        verifyNoInteractions(redissonClient);
    }

    @Test
    void shouldCacheDatabaseMissAsShortLivedNullMarker() throws InterruptedException {
        prepareCacheMissAndLock();

        AiModel result = query(id -> null);

        assertThat(result).isNull();
        ArgumentCaptor<Long> ttl = ArgumentCaptor.forClass(Long.class);
        verify(valueOperations).set(eq(KEY), eq(""), ttl.capture(), eq(TimeUnit.MINUTES));
        assertThat(ttl.getValue()).isBetween(2L, 4L);
        verify(lock).unlock();
    }

    @Test
    void shouldCacheDatabaseValueWithRandomizedTtl() throws InterruptedException {
        prepareCacheMissAndLock();
        AiModel model = new AiModel().setId(99L).setName("test-model").setStatus(1);

        AiModel result = query(id -> model);

        assertThat(result).isSameAs(model);
        ArgumentCaptor<Long> ttl = ArgumentCaptor.forClass(Long.class);
        verify(valueOperations).set(eq(KEY), anyString(), ttl.capture(), eq(TimeUnit.MINUTES));
        assertThat(ttl.getValue()).isBetween(10L, 15L);
        verify(lock).unlock();
    }

    @Test
    void shouldRandomizeHotListTtl() {
        ArgumentCaptor<Long> ttl = ArgumentCaptor.forClass(Long.class);

        cacheClient.setWithRandomTtl("cache:ai-model:hot:0:all:1", "[]", 60, 30, TimeUnit.SECONDS);

        verify(valueOperations).set(
                eq("cache:ai-model:hot:0:all:1"),
                anyString(),
                ttl.capture(),
                eq(TimeUnit.SECONDS));
        assertThat(ttl.getValue()).isBetween(60L, 90L);
        verify(redissonClient, never()).getLock(anyString());
    }

    @Test
    void shouldReturnFreshLogicalListWithoutRebuilding() {
        String key = "cache:ai-model:hot:0:all:1";
        String value = JSONUtil.toJsonStr(Map.of(
                "data", List.of(new AiModel().setId(1L).setName("old")),
                "expireAt", System.currentTimeMillis() + 60_000));
        when(valueOperations.get(key)).thenReturn(value);
        AtomicBoolean databaseCalled = new AtomicBoolean(false);

        List<AiModel> result = queryHotList(key, () -> {
            databaseCalled.set(true);
            return List.of(new AiModel().setId(2L));
        });

        assertThat(result).extracting(AiModel::getId).containsExactly(1L);
        assertThat(databaseCalled).isFalse();
        verifyNoInteractions(redissonClient);
    }

    @Test
    void shouldReturnExpiredListAndRefreshIt() throws InterruptedException {
        String key = "cache:ai-model:hot:0:all:1";
        String lockKey = "lock:cache:ai-model:hot:0:all:1";
        String expired = JSONUtil.toJsonStr(Map.of(
                "data", List.of(new AiModel().setId(1L).setName("stale")),
                "expireAt", System.currentTimeMillis() - 1_000));
        when(valueOperations.get(key)).thenReturn(expired);
        when(redissonClient.getLock(lockKey)).thenReturn(lock);
        when(lock.tryLock(0L, 10L, TimeUnit.SECONDS)).thenReturn(true);
        when(lock.isHeldByCurrentThread()).thenReturn(true);

        List<AiModel> result = queryHotList(
                key,
                () -> List.of(new AiModel().setId(2L).setName("fresh")));

        assertThat(result).extracting(AiModel::getId).containsExactly(1L);
        verify(valueOperations).set(
                eq(key),
                anyString(),
                eq(600_000L),
                eq(TimeUnit.MILLISECONDS));
        verify(lock).unlock();
    }

    private void prepareCacheMissAndLock() throws InterruptedException {
        when(valueOperations.get(KEY)).thenReturn(null).thenReturn(null);
        when(redissonClient.getLock(LOCK_KEY)).thenReturn(lock);
        when(lock.tryLock(anyLong(), anyLong(), eq(TimeUnit.SECONDS))).thenReturn(true);
        when(lock.isHeldByCurrentThread()).thenReturn(true);
    }

    private AiModel query(java.util.function.Function<Long, AiModel> fallback) {
        return cacheClient.queryWithPassThroughAndMutex(
                99L,
                AiModel.class,
                "cache:ai-model:",
                "lock:cache:ai-model:",
                10,
                2,
                5,
                TimeUnit.MINUTES,
                fallback);
    }

    private List<AiModel> queryHotList(
            String key,
            java.util.function.Supplier<List<AiModel>> fallback) {
        return cacheClient.queryListWithLogicalExpire(
                key,
                "lock:" + key,
                AiModel.class,
                Duration.ofSeconds(60),
                Duration.ofSeconds(30),
                Duration.ofMinutes(10),
                fallback);
    }
}
