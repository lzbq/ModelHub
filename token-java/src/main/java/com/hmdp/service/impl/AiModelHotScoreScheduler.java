package com.hmdp.service.impl;

import com.hmdp.config.AiModelHotScoreProperties;
import com.hmdp.service.AiModelPopularityService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
/*
* AiModelHotScoreScheduler 是热度系统的定时触发器：它每隔一小段时间把本机计数刷到 Redis，并按 cron 定时刷新模型热度分；
* 刷新热度分时用 Redisson 分布式锁，确保多实例部署下只有一个节点真正执行数据库更新。
* */
@Slf4j
@Component
public class AiModelHotScoreScheduler {

    private static final String REFRESH_LOCK = "lock:ai-model:hot-score:refresh";

    @Resource
    private AiModelPopularityService aiModelPopularityService;
    @Resource
    private AiModelHotScoreProperties properties;
    @Resource
    private RedissonClient redissonClient;

    //1. 定时刷本机指标到 Redis
    //@Scheduled：方法会被 Spring 定时执行，前提是项目启用了定时任务，比如有 @EnableScheduling。
    @Scheduled(
            fixedDelayString = "${modelhub.hot-score.metrics-flush-interval-ms:1000}",//上一次执行结束后，再等待一秒执行下一次。
            initialDelayString = "${modelhub.hot-score.metrics-flush-interval-ms:1000}")
    public void flushMetrics() {
        aiModelPopularityService.flushPendingMetrics();
    }

    //2. 定时刷新热度分
    @Scheduled(cron = "${modelhub.hot-score.refresh-cron:0 5 * * * *}")//每小时第 5 分钟的第 0 秒执行 例如：10:05:00
    public void refreshScores() {
        if (!properties.isEnabled()) {
            return;
        }
        RLock lock = redissonClient.getLock(REFRESH_LOCK);//同一时间只有一个实例执行 refreshHotScores()
        if (!lock.tryLock()) {
            log.debug("skip AI model hot-score refresh because another instance owns the lock");
            return;
        }
        try {
            aiModelPopularityService.refreshHotScores();
        } finally {
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }
}
