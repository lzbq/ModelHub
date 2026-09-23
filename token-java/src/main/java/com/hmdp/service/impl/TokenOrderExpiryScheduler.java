package com.hmdp.service.impl;

import com.hmdp.entity.TokenOrder;
import com.hmdp.service.ITokenOrderService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/** Bounded fallback for lost or failed delayed-message delivery. */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "modelhub.order", name = "cleanup-enabled", havingValue = "true", matchIfMissing = true)
public class TokenOrderExpiryScheduler {
    @Resource
    private ITokenOrderService tokenOrderService;
    @Value("${modelhub.order.timeout-seconds:1800}")
    private long timeoutSeconds = 1800;

    @Scheduled(fixedDelayString = "${modelhub.order.cleanup-interval-ms:60000}")
    public void cancelExpiredOrders() {
        List<TokenOrder> expired;
        try {
            expired = tokenOrderService.lambdaQuery().eq(TokenOrder::getStatus, 1)
                    .le(TokenOrder::getCreateTime, LocalDateTime.now().minusSeconds(timeoutSeconds))
                    .orderByAsc(TokenOrder::getCreateTime).last("LIMIT 100").list();
        } catch (RuntimeException ex) {
            log.error("failed to scan expired token orders; next cleanup will retry", ex);
            return;
        }
        for (TokenOrder order : expired) {
            try {
                // Goes through the service proxy, preserving its transaction and status CAS.
                tokenOrderService.releaseTimeoutOrder(order.getId());
            } catch (RuntimeException ex) {
                log.error("failed to cancel expired token order {}; next cleanup will retry", order.getId(), ex);
            }
        }
    }
}
