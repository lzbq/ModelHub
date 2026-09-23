package com.hmdp.service.impl;

import com.hmdp.config.AiModelHotScoreProperties;
import org.springframework.stereotype.Component;

/** 纯热度评分公式独立保留，这样可以在不使用 Redis 的情况下测试权重和衰减。 */
@Component
public class AiModelHotScoreCalculator {

    private final AiModelHotScoreProperties properties;

    public AiModelHotScoreCalculator(AiModelHotScoreProperties properties) {
        this.properties = properties;
    }

    public long calculate(Signals recent, Signals previous) {
        Signals safeRecent = recent == null ? Signals.ZERO : recent;
        Signals safePrevious = previous == null ? Signals.ZERO : previous;
        //指标归一化
        double recentViews = normalize(safeRecent.detailViews(), properties.getDetailViewSaturation());
        double recentPurchases = normalize(safeRecent.purchases(), properties.getPurchaseSaturation());

        double previousViews = normalize(safePrevious.detailViews(), properties.getDetailViewSaturation());
        double previousPurchases = normalize(safePrevious.purchases(), properties.getPurchaseSaturation());
        //计算当前活跃度
        double recentActivity = weightedActivity(recentViews, recentPurchases);
        double previousActivity = weightedActivity(previousViews, previousPurchases);
        double growthSignal = growthSignal(recentActivity, previousActivity);

        double weightedScore = recentActivity + properties.getGrowthWeight() * growthSignal;
        double totalWeight = positive(properties.getDetailViewWeight())
                + positive(properties.getPurchaseWeight())
                + positive(properties.getGrowthWeight());
        if (totalWeight == 0D) {
            return 0L;
        }
        double normalizedScore = clamp(weightedScore / totalWeight, 0D, 1D);
        return Math.round(normalizedScore * Math.max(0L, properties.getMaxScore()));
    }
    //时间衰减函数
    public double decayFactor(double ageHours) {
        double halfLife = properties.getHalfLifeHours();
        if (halfLife <= 0D) {
            throw new IllegalArgumentException("modelhub.hot-score.half-life-hours must be positive");
        }
        return Math.pow(0.5D, Math.max(0D, ageHours) / halfLife);//decay = 0.5 ^ (ageHours / 12)
    }
    //按权重加权
    private double weightedActivity(double views, double purchases) {
        return positive(properties.getDetailViewWeight()) * views
                + positive(properties.getPurchaseWeight()) * purchases;
    }

    private double growthSignal(double recentActivity, double previousActivity) {
        if (recentActivity == 0D && previousActivity == 0D) {//最近和之前都没数据：增长信号是 0
            return 0D;
        }
        if (previousActivity == 0D) {//之前没数据，现在有数据：认为是强增长，返回 1
            return 1D;
        }
        double maxGrowthRate = properties.getMaxGrowthRate();
        if (maxGrowthRate <= 0D) {
            throw new IllegalArgumentException("modelhub.hot-score.max-growth-rate must be positive");
        }
        double growthRate = (recentActivity - previousActivity) / previousActivity;
        return clamp(growthRate / maxGrowthRate, -1D, 1D);//如果最近活跃度比上一窗口增长 300%，增长信号就是 1。如果下降，也可能是负数，最低到 -1。
    }

    private double normalize(double value, double saturation) {
        if (value <= 0D) {
            return 0D;
        }
        if (saturation <= 0D) {
            throw new IllegalArgumentException("hot-score saturation must be positive");
        }
        //归一化值 = log(1 + 当前值) / log(1 + 饱和值)
        return clamp(Math.log1p(value) / Math.log1p(saturation), 0D, 1D);
    }

    private static double positive(double value) {
        return Math.max(0D, value);
    }

    private static double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(max, value));
    }

    //这是一个不可变数据结构，用来表示某个模型在某个窗口内的两类指标。
    public record Signals(double detailViews, double purchases) {
        public static final Signals ZERO = new Signals(0D, 0D);

        public Signals add(MetricType metricType, double value) {
            return switch (metricType) {
                case DETAIL_VIEW -> new Signals(detailViews + value, purchases);
                case PURCHASE -> new Signals(detailViews, purchases + value);
            };
        }
    }

    public enum MetricType {
        DETAIL_VIEW("view"),
        PURCHASE("purchase");

        private final String redisName;

        MetricType(String redisName) {
            this.redisName = redisName;
        }

        public String redisName() {
            return redisName;
        }
    }
}
