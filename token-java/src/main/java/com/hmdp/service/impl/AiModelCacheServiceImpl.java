package com.hmdp.service.impl;

import com.github.benmanes.caffeine.cache.Cache;
import com.hmdp.entity.AiModel;
import com.hmdp.service.AiModelCacheService;
import jakarta.annotation.Resource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.Collection;
import java.util.List;
import java.util.Objects;

import static com.hmdp.utils.AiModelCacheKeys.HOT_LIST_VERSION;
import static com.hmdp.utils.AiModelCacheKeys.MODEL_DETAIL_PREFIX;

@Service
public class AiModelCacheServiceImpl implements AiModelCacheService {
    /*
    * 集中管理模型缓存失效。更新节点删除 Redis 详情、递增榜单版本并清理本机 Caffeine；MQ 消费节点只清理本机 Caffeine。
    * */

    @Resource(name = "hotAiModelDetailLocalCache")
    private Cache<Long, AiModel> hotDetailLocalCache;
    @Resource(name = "hotAiModelListLocalCache")
    private Cache<String, List<AiModel>> hotListLocalCache;
    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Override
    public void evictModelCache(Long modelId) {
        evictModelCaches(modelId == null ? List.of() : List.of(modelId));
    }

    @Override
    public void evictModelCaches(Collection<Long> modelIds) {
        List<Long> ids = normalizeIds(modelIds);
        if (ids.isEmpty()) {
            return;
        }
        evictLocalModelCaches(ids);
        //根据一批模型 ID，拼出对应的模型详情缓存 key，然后从 Redis 中删除这些缓存。
        stringRedisTemplate.delete(ids.stream().map(id -> MODEL_DETAIL_PREFIX + id).toList());
        //递增热门榜版本号。
        stringRedisTemplate.opsForValue().increment(HOT_LIST_VERSION);
    }

    @Override
    public void evictLocalModelCache(Long modelId) {
        evictLocalModelCaches(modelId == null ? List.of() : List.of(modelId));
    }

    @Override
    public void evictLocalModelCaches(Collection<Long> modelIds) {
        List<Long> ids = normalizeIds(modelIds);
        if (ids.isEmpty()) {
            return;
        }
        ids.forEach(hotDetailLocalCache::invalidate);
        hotListLocalCache.invalidateAll();
    }

    private static List<Long> normalizeIds(Collection<Long> modelIds) {
        if (modelIds == null || modelIds.isEmpty()) {
            return List.of();
        }
        return modelIds.stream().filter(Objects::nonNull).distinct().toList();
    }
}
