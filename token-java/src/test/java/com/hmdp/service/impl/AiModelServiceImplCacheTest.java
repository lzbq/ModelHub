package com.hmdp.service.impl;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.hmdp.dto.Result;
import com.hmdp.entity.AiModel;
import com.hmdp.service.AiModelPopularityService;
import com.hmdp.utils.CacheClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AiModelServiceImplCacheTest {

    @Mock
    private CacheClient cacheClient;
    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private AiModelPopularityService aiModelPopularityService;

    private AiModelServiceImpl service;
    private Cache<Long, AiModel> hotDetailCache;
    private Cache<String, List<AiModel>> hotListCache;

    @BeforeEach
    void setUp() {
        service = new AiModelServiceImpl();
        hotDetailCache = Caffeine.newBuilder().maximumSize(100).build();
        hotListCache = Caffeine.newBuilder().maximumSize(100).build();
        ReflectionTestUtils.setField(service, "hotDetailLocalCache", hotDetailCache);
        ReflectionTestUtils.setField(service, "hotListLocalCache", hotListCache);
        ReflectionTestUtils.setField(service, "cacheClient", cacheClient);
        ReflectionTestUtils.setField(service, "stringRedisTemplate", stringRedisTemplate);
        ReflectionTestUtils.setField(service, "aiModelPopularityService", aiModelPopularityService);
        ReflectionTestUtils.setField(service, "hotScoreThreshold", 8_000L);
    }

    @Test
    void shouldPutHotModelDetailIntoCaffeine() {
        AiModel model = model(1L, 9_800L);
        mockDetailLoad(1L, model);

        Result result = service.queryDetail(1L);

        assertThat(result.getSuccess()).isTrue();
        assertThat(hotDetailCache.getIfPresent(1L)).isSameAs(model);
        verify(aiModelPopularityService).recordDetailView(1L);
    }

    @Test
    void shouldKeepOrdinaryModelDetailOutOfCaffeine() {
        AiModel model = model(4L, 7_600L);
        mockDetailLoad(4L, model);

        Result result = service.queryDetail(4L);

        assertThat(result.getSuccess()).isTrue();
        assertThat(hotDetailCache.getIfPresent(4L)).isNull();
        verify(aiModelPopularityService).recordDetailView(4L);
    }

    @Test
    void caffeineHitShouldStillRecordDetailView() {
        AiModel model = model(1L, 9_800L);
        hotDetailCache.put(1L, model);

        Result result = service.queryDetail(1L);

        assertThat(result.getData()).isSameAs(model);
        verify(aiModelPopularityService).recordDetailView(1L);
        verifyNoInteractions(stringRedisTemplate, cacheClient);
    }

    @Test
    void shouldReturnHotListFromCaffeineWithoutCallingRedis() {
        List<AiModel> models = List.of(model(1L, 9_800L), model(3L, 9_900L));
        hotListCache.put("all:1", models);

        Result result = service.queryHot(null, 1);

        assertThat(result.getData()).isSameAs(models);
        verifyNoInteractions(stringRedisTemplate, cacheClient);
    }

    private void mockDetailLoad(Long id, AiModel model) {
        when(cacheClient.queryWithPassThroughAndMutex(
                eq(id),
                eq(AiModel.class),
                anyString(),
                anyString(),
                anyLong(),
                anyLong(),
                anyLong(),
                eq(TimeUnit.MINUTES),
                any())).thenReturn(model);
    }

    private AiModel model(Long id, Long hotScore) {
        return new AiModel()
                .setId(id)
                .setName("model-" + id)
                .setStatus(1)
                .setHotScore(hotScore);
    }
}
