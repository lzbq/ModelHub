package com.hmdp.mq;

import com.hmdp.service.ITokenOrderService;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;

@Component
@RocketMQMessageListener(topic = TokenOrderTimeoutMqConstants.TOPIC,
        consumerGroup = TokenOrderTimeoutMqConstants.CONSUMER_GROUP)
public class TokenOrderTimeoutConsumer implements RocketMQListener<TokenOrderTimeoutMessage> {
    @Resource
    private ITokenOrderService tokenOrderService;

    @Override
    public void onMessage(TokenOrderTimeoutMessage message) {
        if (message != null && message.getOrderId() != null) {
            tokenOrderService.releaseTimeoutOrder(message.getOrderId());
        }
    }
}
