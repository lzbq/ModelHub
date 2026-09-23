package com.hmdp.service;

import java.util.Collection;

/** 统一删除 AI 模型的 JVM 本地缓存和 Redis 分布式缓存。 */
public interface AiModelCacheService {

    void evictModelCache(Long modelId);

    void evictModelCaches(Collection<Long> modelIds);

    /** Clear only this JVM's local caches when consuming an MQ broadcast. */
    void evictLocalModelCache(Long modelId);

    void evictLocalModelCaches(Collection<Long> modelIds);
}
