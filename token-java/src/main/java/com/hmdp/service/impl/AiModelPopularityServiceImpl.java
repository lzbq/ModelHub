package com.hmdp.service.impl;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.hmdp.config.AiModelHotScoreProperties;
import com.hmdp.entity.AiModel;
import com.hmdp.mapper.AiModelMapper;
import com.hmdp.mq.AiModelCacheProducer;
import com.hmdp.service.AiModelCacheService;
import com.hmdp.service.AiModelPopularityService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import static com.hmdp.service.impl.AiModelHotScoreCalculator.MetricType;
/*
* 记录行为指标、把指标刷到 Redis、定时根据 Redis 指标重算数据库里的 AiModel.hotScore。
* */
@Slf4j
@Service
public class AiModelPopularityServiceImpl implements AiModelPopularityService {

    private static final String METRIC_PREFIX = "metrics:ai-model:";
    private static final DateTimeFormatter HOUR_FORMATTER =
            DateTimeFormatter.ofPattern("yyyyMMddHH").withZone(ZoneOffset.UTC);
    //1. 本地计数缓冲 这里维护的是 JVM 内存里的临时计数器
    //结构大概是：指标类型 -> 模型ID -> 计数
    private final Map<MetricType, ConcurrentHashMap<Long, AtomicLong>> pendingCounters =
            new EnumMap<>(MetricType.class);

    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private AiModelMapper aiModelMapper;
    @Resource
    private AiModelHotScoreCalculator calculator;//真正计算热度分。
    @Resource
    private AiModelHotScoreProperties properties;//读取热度配置，比如窗口、权重、半衰期。
    @Resource
    private AiModelCacheService aiModelCacheService;
    @Resource
    private AiModelCacheProducer aiModelCacheProducer;

    public AiModelPopularityServiceImpl() {
        for (MetricType metricType : MetricType.values()) {
            pendingCounters.put(metricType, new ConcurrentHashMap<>());//给每种指标初始化一个 ConcurrentHashMap。
        }
    }

    @Override
    public void recordDetailView(Long modelId) {
        record(MetricType.DETAIL_VIEW, modelId);
    }

    @Override
    public void recordPurchase(Long modelId) {
        record(MetricType.PURCHASE, modelId);
    }

    private void record(MetricType metricType, Long modelId) {
        if (!properties.isEnabled() || modelId == null || modelId <= 0) {
            return;
        }
        //请求发生时不会立刻写 Redis，只是在本机内存里加 1。这样可以减少高频行为对 Redis 的直接写入压力。
        pendingCounters.get(metricType)
                .computeIfAbsent(modelId, ignored -> new AtomicLong())
                .incrementAndGet();
    }

    /**
     * 在这个 JVM 中合并高频事件，并为每个活跃的模型/类型写一个 ZINCRBY。
     * Redis 异常时计数会放回本地重试，但进程退出仍可能丢失尚未落盘的累计量。
     */
    //定时任务每隔一段时间把本机计数批量刷入 Redis。
    @Override
    public void flushPendingMetrics() {//把本机积累的计数刷到 Redis：
        if (!properties.isEnabled()) {
            return;
        }
        Instant currentHour = Instant.now().truncatedTo(ChronoUnit.HOURS);
        for (MetricType metricType : MetricType.values()) {
            flushMetric(metricType, currentHour);
        }
    }

    private void flushMetric(MetricType metricType, Instant currentHour) {
        String redisKey = metricKey(metricType, currentHour);
        boolean wroteAny = false;
        for (Map.Entry<Long, AtomicLong> entry : pendingCounters.get(metricType).entrySet()) {
            long count = entry.getValue().getAndSet(0L);//先把本地计数清零，再写 Redis。
            if (count <= 0L) {
                continue;
            }
            try {
                stringRedisTemplate.opsForZSet()
                        .incrementScore(redisKey, entry.getKey().toString(), count);
                wroteAny = true;
            } catch (RuntimeException ex) {
                entry.getValue().addAndGet(count);//如果 Redis 写失败，会把计数加回去
                log.warn("flush AI model popularity metric failed, key={}, modelId={}",
                        redisKey, entry.getKey(), ex);
            }
        }
        if (wroteAny) {
            int minimumRetention = Math.max(2, properties.getWindowHours() * 2 + 2);
            int retentionHours = Math.max(properties.getMetricRetentionHours(), minimumRetention);
            try {
                stringRedisTemplate.expire(redisKey, Duration.ofHours(retentionHours));
            } catch (RuntimeException ex) {
                // The metric has already been persisted. A later write will retry setting its TTL.
                log.warn("set AI model popularity metric TTL failed, key={}", redisKey, ex);
            }
        }
    }

    /**
     * 使用最近完成的时间窗口和前一个相同长度的窗口。
     * 在评分之前，每个按小时分的区间都会按配置的半衰期打折。
     */
    //另一个定时任务周期性读取 Redis 最近窗口数据。
    @Override
    @Transactional
    public void refreshHotScores() {
        if (!properties.isEnabled()) {
            return;
        }
        int windowHours = properties.getWindowHours();
        if (windowHours <= 0 || windowHours > 168) {
            throw new IllegalArgumentException("modelhub.hot-score.window-hours must be between 1 and 168");
        }

        Instant currentHour = Instant.now().truncatedTo(ChronoUnit.HOURS);
        //结构：modelId=101 -> Signals(detailViews=9200.3, purchases=54.2)...
        Map<Long, AiModelHotScoreCalculator.Signals> recent = new ConcurrentHashMap<>();//最近窗口，比如最近 24 个已完成小时。
        Map<Long, AiModelHotScoreCalculator.Signals> previous = new ConcurrentHashMap<>();//再往前的 24 小时。

        for (int offset = 1; offset <= windowHours * 2; offset++) {
            Map<Long, AiModelHotScoreCalculator.Signals> target =
                    offset <= windowHours ? recent : previous;
            double ageInsideWindow = ((offset - 1) % windowHours) + 0.5D;
            double decay = calculator.decayFactor(ageInsideWindow);//对每小时数据做时间衰减。
            Instant bucket = currentHour.minus(offset, ChronoUnit.HOURS);
            for (MetricType metricType : MetricType.values()) {
                addBucket(metricKey(metricType, bucket), metricType, decay, target);
            }
        }
        if (recent.isEmpty() && previous.isEmpty()) {
            log.info("skip AI model hot-score refresh because no metric window has been collected yet");
            return;
        }

        List<AiModel> models = aiModelMapper.selectList(
                Wrappers.<AiModel>lambdaQuery().select(AiModel::getId, AiModel::getHotScore));
        List<Long> changedModelIds = new ArrayList<>();
        for (AiModel model : models) {
            //重算每个模型的新分数
            long newScore = calculator.calculate(
                    recent.getOrDefault(model.getId(), AiModelHotScoreCalculator.Signals.ZERO),
                    previous.getOrDefault(model.getId(), AiModelHotScoreCalculator.Signals.ZERO));
            if (model.getHotScore() != null && model.getHotScore() == newScore) {
                continue;
            }
            int updated = aiModelMapper.update(null,
                    Wrappers.<AiModel>lambdaUpdate()
                            .set(AiModel::getHotScore, newScore)
                            .eq(AiModel::getId, model.getId()));
            if (updated > 0) {
                changedModelIds.add(model.getId());
            }
        }

        //数据库 hotScore 更新成功、清理本机缓存、发送 MQ 通知其他节点清缓存
        if (!changedModelIds.isEmpty()) {
            List<Long> immutableIds = List.copyOf(changedModelIds);
            afterCommit(() -> {
                aiModelCacheService.evictModelCaches(immutableIds);
                //遍历所有发生变化的模型 ID，并逐个发送缓存失效消息
                immutableIds.forEach(aiModelCacheProducer::sendCacheInvalidation);
            });
        }
        log.info("refreshed AI model hot scores, modelCount={}, changedCount={}",
                models.size(), changedModelIds.size());
    }

    private void addBucket(
            String redisKey,
            MetricType metricType,
            double decay,
            Map<Long, AiModelHotScoreCalculator.Signals> target) {
        Set<ZSetOperations.TypedTuple<String>> tuples =
                stringRedisTemplate.opsForZSet().rangeWithScores(redisKey, 0, -1);//负责读取某个 Redis ZSet
        if (tuples == null || tuples.isEmpty()) {
            return;
        }
        for (ZSetOperations.TypedTuple<String> tuple : tuples) {
            if (tuple.getValue() == null || tuple.getScore() == null) {
                continue;
            }
            try {
                Long modelId = Long.valueOf(tuple.getValue());
                double decayedValue = tuple.getScore() * decay;//把每个模型的指标乘以衰减系数
                //compute 的作用：把当前 Redis 小时桶读出来的值，累加到对应模型的 Signals 里。
                target.compute(modelId, (ignored, signals) ->//signals：这个模型当前已经累计的指标值
                        (signals == null ? AiModelHotScoreCalculator.Signals.ZERO : signals)
                                .add(metricType, decayedValue));
            } catch (NumberFormatException ex) {
                log.warn("ignore invalid AI model metric member, key={}, member={}",
                        redisKey, tuple.getValue());
            }
        }
    }

    private static String metricKey(MetricType metricType, Instant hour) {
        return METRIC_PREFIX + metricType.redisName() + ":" + HOUR_FORMATTER.format(hour);//例如：metrics:ai-model:view:2026091210
    }

    private static void afterCommit(Runnable action) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            action.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                action.run();
            }
        });
    }
}
