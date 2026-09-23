package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import com.hmdp.entity.TokenOrder;
import com.hmdp.service.ITokenOrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.List;

import static com.hmdp.service.impl.FluentChainMocks.chainMock;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class TokenOrderExpirySchedulerTest {
    private TokenOrderExpiryScheduler scheduler;
    private ITokenOrderService orders;
    private LambdaQueryChainWrapper<TokenOrder> query;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        scheduler = new TokenOrderExpiryScheduler();
        orders = mock(ITokenOrderService.class);
        query = chainMock(LambdaQueryChainWrapper.class);
        ReflectionTestUtils.setField(scheduler, "tokenOrderService", orders);
        ReflectionTestUtils.setField(scheduler, "timeoutSeconds", 300L);
        when(orders.lambdaQuery()).thenReturn(query);
    }

    @Test
    void scansOnlyUnpaidExpiredOrdersWithBoundedBatchAndUsesServiceTransaction() {
        when(query.list()).thenReturn(List.of(new TokenOrder().setId(10L), new TokenOrder().setId(11L)));
        LocalDateTime before = LocalDateTime.now().minusSeconds(300);

        scheduler.cancelExpiredOrders();

        verify(query).eq(any(), eq(1));
        verify(query).last("LIMIT 100");
        ArgumentCaptor<Object> cutoff = ArgumentCaptor.forClass(Object.class);
        verify(query).le(any(), cutoff.capture());
        assertThat((LocalDateTime) cutoff.getValue()).isBetween(before, LocalDateTime.now().minusSeconds(300));
        verify(orders).releaseTimeoutOrder(10L);
        verify(orders).releaseTimeoutOrder(11L);
    }

    @Test
    void oneCancellationFailureDoesNotBlockTheRemainingOrders() {
        when(query.list()).thenReturn(List.of(new TokenOrder().setId(10L), new TokenOrder().setId(11L)));
        doThrow(new IllegalStateException("transient failure")).when(orders).releaseTimeoutOrder(10L);

        scheduler.cancelExpiredOrders();

        verify(orders).releaseTimeoutOrder(11L);
    }
}
