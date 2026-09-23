package com.hmdp.mq;

import jakarta.annotation.Resource;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.stereotype.Component;

@Component
public class AiModelCacheProducer {

    @Resource
    private RocketMQTemplate rocketMQTemplate;

    public void sendCacheInvalidation(Long modelId) {
        rocketMQTemplate.convertAndSend(
                AiModelCacheMqConstants.TOPIC,
                new AiModelCacheMessage(modelId));
    }
}
