package com.hmdp.mq;

import com.hmdp.entity.TokenOrder;
import com.hmdp.service.ITokenOrderService;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;

@Component
@RocketMQMessageListener(topic = TokenOrderMqConstants.TOPIC,
        consumerGroup = TokenOrderMqConstants.CONSUMER_GROUP)
public class TokenOrderConsumer implements RocketMQListener<TokenOrderMessage> {
    @Resource
    private ITokenOrderService tokenOrderService;

    @Override
    public void onMessage(TokenOrderMessage message) {
        if (message == null || message.getOrderId() == null) {
            return;
        }
        tokenOrderService.handleSeckillOrder(new TokenOrder()
                .setId(message.getOrderId())
                .setUserId(message.getUserId())
                .setPackageId(message.getPackageId()));
    }
}
