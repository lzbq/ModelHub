package com.hmdp.service.impl;

import com.hmdp.config.AiModelHotScoreProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AiModelPopularityServiceImplTest {

    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private ZSetOperations<String, String> zSetOperations;

    private AiModelPopularityServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new AiModelPopularityServiceImpl();
        ReflectionTestUtils.setField(service, "stringRedisTemplate", stringRedisTemplate);
        ReflectionTestUtils.setField(service, "properties", new AiModelHotScoreProperties());
        when(stringRedisTemplate.opsForZSet()).thenReturn(zSetOperations);
    }

    @Test
    void shouldCollapseEventsBeforeFlushingHourlyRedisMetrics() {
        service.recordDetailView(7L);
        service.recordDetailView(7L);
        service.recordPurchase(7L);

        service.flushPendingMetrics();

        verify(zSetOperations).incrementScore(
                startsWith("metrics:ai-model:view:"), eq("7"), eq(2D));
        verify(zSetOperations).incrementScore(
                startsWith("metrics:ai-model:purchase:"), eq("7"), eq(1D));
        verify(stringRedisTemplate, times(2))
                .expire(startsWith("metrics:ai-model:"), any(Duration.class));
    }
}
