package com.hmdp.mq;

import com.hmdp.entity.TokenOrder;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;

@Slf4j
@Component
public class TokenOrderProducer {
    @Resource
    private RocketMQTemplate rocketMQTemplate;

    public void send(TokenOrder order) {
        rocketMQTemplate.syncSend(TokenOrderMqConstants.TOPIC,
                new TokenOrderMessage(order.getId(), order.getUserId(), order.getPackageId()));
        log.debug("send token order, orderId={}", order.getId());
    }
}
