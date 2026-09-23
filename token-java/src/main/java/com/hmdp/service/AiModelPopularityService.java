package com.hmdp.service;

/** Collects recent model activity and periodically materializes it into tb_ai_model.hot_score. */
public interface AiModelPopularityService {

    void recordDetailView(Long modelId);

    void recordPurchase(Long modelId);

    void flushPendingMetrics();

    void refreshHotScores();
}
