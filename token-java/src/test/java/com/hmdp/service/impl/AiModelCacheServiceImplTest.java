package com.hmdp.service.impl;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.hmdp.entity.AiModel;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AiModelCacheServiceImplTest {

    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;

    private AiModelCacheServiceImpl service;
    private Cache<Long, AiModel> hotDetailCache;
    private Cache<String, List<AiModel>> hotListCache;

    @BeforeEach
    void setUp() {
        service = new AiModelCacheServiceImpl();
        hotDetailCache = Caffeine.newBuilder().build();
        hotListCache = Caffeine.newBuilder().build();
        ReflectionTestUtils.setField(service, "hotDetailLocalCache", hotDetailCache);
        ReflectionTestUtils.setField(service, "hotListLocalCache", hotListCache);
        ReflectionTestUtils.setField(service, "stringRedisTemplate", stringRedisTemplate);
    }

    @Test
    void broadcastInvalidationShouldOnlyClearThisJvm() {
        hotDetailCache.put(1L, new AiModel().setId(1L));
        hotListCache.put("all:1", List.of(new AiModel().setId(1L)));

        service.evictLocalModelCache(1L);

        assertThat(hotDetailCache.getIfPresent(1L)).isNull();
        assertThat(hotListCache.getIfPresent("all:1")).isNull();
        verifyNoInteractions(stringRedisTemplate);
    }

    @Test
    void updateInvalidationShouldClearRedisAndAdvanceVersionOnce() {
        when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);

        service.evictModelCache(1L);

        verify(stringRedisTemplate).delete(List.of("cache:ai-model:1"));
        verify(valueOperations).increment("cache:ai-model:hot:version");
    }

    @Test
    void batchInvalidationShouldDeleteAllDetailsAndAdvanceListVersionOnce() {
        when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
        hotDetailCache.put(1L, new AiModel().setId(1L));
        hotDetailCache.put(2L, new AiModel().setId(2L));
        hotListCache.put("all:1", List.of(new AiModel().setId(1L)));

        service.evictModelCaches(List.of(1L, 2L, 1L));

        assertThat(hotDetailCache.getIfPresent(1L)).isNull();
        assertThat(hotDetailCache.getIfPresent(2L)).isNull();
        assertThat(hotListCache.getIfPresent("all:1")).isNull();
        verify(stringRedisTemplate).delete(List.of("cache:ai-model:1", "cache:ai-model:2"));
        verify(valueOperations).increment("cache:ai-model:hot:version");
    }
}
