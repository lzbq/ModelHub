package com.hmdp.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** 动态 AI 模型热门评分权重、窗口和归一化阈值. */
@Data
@Component
@ConfigurationProperties(prefix = "modelhub.hot-score")
public class AiModelHotScoreProperties {
    //开关和时间窗口
    private boolean enabled = true;//是否启用热度统计
    private int windowHours = 24;//计算最近多少小时的数据，默认 24 小时。
    private int metricRetentionHours = 72;//Redis 指标桶保留多久，默认 72 小时。
    private double halfLifeHours = 12D;//时间衰减半衰期，默认 12 小时；越旧的数据权重越低。
    private long maxScore = 10_000L;//最终热度分上限，默认 10000。
    //热度权重
    private double detailViewWeight = 0.35D;//详情浏览占 35%
    private double purchaseWeight = 0.50D;//购买占 50%
    private double growthWeight = 0.15D;//增长趋势占 15%
    //归一化阈值
    private double detailViewSaturation = 5_000D;//详情浏览达到约 5000 时，浏览指标接近满分。
    private double purchaseSaturation = 100D;//购买达到约 100 时，购买指标接近满分。
    private double maxGrowthRate = 3D;//增长率归一化上限，默认 3 倍增长视为增长信号满值。
}
