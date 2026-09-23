package com.hmdp.mq;

import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;

@Component
public class TokenOrderTimeoutProducer {
    @Resource
    private RocketMQTemplate rocketMQTemplate;
    @Value("${modelhub.order.timeout-seconds:1800}")
    private long timeoutSeconds;

    public void send(Long orderId) {
        rocketMQTemplate.syncSendDelayTimeSeconds(TokenOrderTimeoutMqConstants.TOPIC,
                new TokenOrderTimeoutMessage(orderId), timeoutSeconds);
    }
}
