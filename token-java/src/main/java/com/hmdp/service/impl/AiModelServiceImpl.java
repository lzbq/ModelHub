package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.github.benmanes.caffeine.cache.Cache;
import com.hmdp.dto.Result;
import com.hmdp.entity.AiModel;
import com.hmdp.mapper.AiModelMapper;
import com.hmdp.mq.AiModelCacheProducer;
import com.hmdp.service.AiModelCacheService;
import com.hmdp.service.AiModelPopularityService;
import com.hmdp.service.IAiModelService;
import com.hmdp.utils.CacheClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import jakarta.annotation.Resource;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static com.hmdp.utils.AiModelCacheKeys.HOT_LIST_PREFIX;
import static com.hmdp.utils.AiModelCacheKeys.HOT_LIST_LOCK_PREFIX;
import static com.hmdp.utils.AiModelCacheKeys.HOT_LIST_VERSION;
import static com.hmdp.utils.AiModelCacheKeys.MODEL_DETAIL_PREFIX;
import static com.hmdp.utils.AiModelCacheKeys.MODEL_DETAIL_LOCK_PREFIX;

@Service
public class AiModelServiceImpl extends ServiceImpl<AiModelMapper, AiModel> implements IAiModelService {
    /*
     * 模型详情、热门模型榜单、搜索和更新。普通详情使用 Redis；达到热度阈值的详情增加 Caffeine；榜单使用 Caffeine + Redis 逻辑过期；更新成功后触发缓存失效和 MQ 广播。
     * */
    private static final int PAGE_SIZE = 10;
    @Resource(name = "hotAiModelDetailLocalCache")
    private Cache<Long, AiModel> hotDetailLocalCache;
    @Resource(name = "hotAiModelListLocalCache")
    private Cache<String, List<AiModel>> hotListLocalCache;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private AiModelCacheService aiModelCacheService;
    @Resource
    private AiModelCacheProducer aiModelCacheProducer;
    @Resource
    private CacheClient cacheClient;
    @Resource
    private AiModelPopularityService aiModelPopularityService;
    @Value("${modelhub.cache.ai-model.hot-score-threshold:8000}")
    private long hotScoreThreshold;

    /*
    * 查询模型详情
    * */
    @Override
    public Result queryDetail(Long id) {
        //1.先查本机 Caffeine 热点详情缓存。
        AiModel model = hotDetailLocalCache.getIfPresent(id);
        if (model != null) {
            aiModelPopularityService.recordDetailView(id);
            return Result.ok(model);
        }
        //2.未命中再通过 CacheClient 查 Redis。
        model = cacheClient.queryWithPassThroughAndMutex(
                id,
                AiModel.class,
                MODEL_DETAIL_PREFIX,
                MODEL_DETAIL_LOCK_PREFIX,
                10,
                2,
                5,
                TimeUnit.MINUTES,
                this::getById);
        if (model == null || model.getStatus() == null || model.getStatus() != 1) {
            return Result.fail("model not found");
        }
        //3.如果模型 hotScore >= hotScoreThreshold，再放入本机热点缓存。
        if (isHotModel(model)) {
            hotDetailLocalCache.put(id, model);
        }
        aiModelPopularityService.recordDetailView(id);
        return Result.ok(model);
    }
    /*
    * 查询热门模型榜单
    * */
    @Override
    public Result queryHot(String category, Integer current) {
        //支持按 category 分类和分页，默认第 1 页，每页 10 条。
        int pageNo = current == null || current < 1 ? 1 : current;
        String normalizedCategory = StringUtils.hasText(category) ? category.trim() : "all";
        String localKey = normalizedCategory + ":" + pageNo;
        //1.先查本机 Caffeine 热门榜缓存。
        List<AiModel> localRecords = hotListLocalCache.getIfPresent(localKey);
        if (localRecords != null) {
            return Result.ok(localRecords);
        }
        String version = stringRedisTemplate.opsForValue().get(HOT_LIST_VERSION);
        String key = HOT_LIST_PREFIX + (version == null ? "0" : version)
                + ":" + normalizedCategory + ":" + pageNo;
        //2.未命中后查 Redis 逻辑过期缓存。
        List<AiModel> records = cacheClient.queryListWithLogicalExpire(
                key,
                HOT_LIST_LOCK_PREFIX + (version == null ? "0" : version)
                        + ":" + normalizedCategory + ":" + pageNo,
                AiModel.class,
                Duration.ofSeconds(60),
                Duration.ofSeconds(30),
                Duration.ofMinutes(10),
                () -> queryHotFromDatabase(normalizedCategory, pageNo));
        hotListLocalCache.put(localKey, records);
        return Result.ok(records);
    }
    //查询状态为上架的 AI 模型；如果指定了分类，就只查这个分类；然后按热度分从高到低排序，分页返回。
    private List<AiModel> queryHotFromDatabase(String normalizedCategory, int pageNo) {
        //SELECT * FROM tb_ai_model WHERE status = 1
        //  -- 如果 category 不是 all，再加这个条件
        //  AND category = ? ORDER BY hot_score DESC LIMIT ?, ?
        //用于创建一个 Lambda 查询构造器。
        return lambdaQuery()
                .eq(AiModel::getStatus, 1)
                .eq(!"all".equals(normalizedCategory), AiModel::getCategory, normalizedCategory)
                .orderByDesc(AiModel::getHotScore)
                .page(new Page<>(pageNo, PAGE_SIZE))
                .getRecords();
    }

    private boolean isHotModel(AiModel model) {
        return model.getHotScore() != null && model.getHotScore() >= hotScoreThreshold;
    }
    /*
    * 关键词搜索
    * */
    @Override
    public Result search(String keyword, Integer current) {
        //如果关键词为空，退化为热门榜查询。
        if (!StringUtils.hasText(keyword)) {
            return queryHot(null, current);
        }
        //在 name、provider、description 中做模糊匹配。
        int pageNo = current == null || current < 1 ? 1 : current;
        Page<AiModel> page = lambdaQuery()
                .eq(AiModel::getStatus, 1)//只查上架模型，也就是 status = 1。
                .and(q -> q.like(AiModel::getName, keyword.trim())
                        .or().like(AiModel::getProvider, keyword.trim())
                        .or().like(AiModel::getDescription, keyword.trim()))
                .orderByDesc(AiModel::getHotScore)
                .page(new Page<>(pageNo, PAGE_SIZE));
        return Result.ok(page.getRecords(), page.getTotal());
    }

    /**
     * 缓存一致性逻辑：更新 DB，事务提交后清理本机缓存并广播。
     */
    @Override
    @Transactional
    public Result updateModel(AiModel model) {
        //校验 model.id 必须存在。
        if (model == null || model.getId() == null) {
            return Result.fail("model id is required");
        }
        if (!updateById(model)) {
            return Result.fail("model not found or update failed");
        }
        //事务提交后才清理缓存
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                //删除当前节点本地缓存和 Redis热点model详情缓存。
                aiModelCacheService.evictModelCache(model.getId());
                //发送 RocketMQ 广播，让其他应用节点清理自己的本地 Caffeine 缓存。
                aiModelCacheProducer.sendCacheInvalidation(model.getId());
            }
        });
        return Result.ok();
    }
}
