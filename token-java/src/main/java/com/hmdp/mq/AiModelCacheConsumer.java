package com.hmdp.mq;

import com.hmdp.service.AiModelCacheService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.spring.annotation.MessageModel;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.stereotype.Component;

/** 广播模式保证每个应用实例都能清理自己的 Caffeine。 */
@Slf4j
@Component
@RocketMQMessageListener(
        topic = AiModelCacheMqConstants.TOPIC,
        consumerGroup = AiModelCacheMqConstants.CONSUMER_GROUP,
        messageModel = MessageModel.BROADCASTING
)
public class AiModelCacheConsumer implements RocketMQListener<AiModelCacheMessage> {

    @Resource
    private AiModelCacheService aiModelCacheService;

    @Override
    public void onMessage(AiModelCacheMessage message) {
        if (message == null || message.getModelId() == null) {
            return;
        }
        log.info("received AI model cache invalidation broadcast, modelId={}", message.getModelId());
        aiModelCacheService.evictLocalModelCache(message.getModelId());
    }
}
