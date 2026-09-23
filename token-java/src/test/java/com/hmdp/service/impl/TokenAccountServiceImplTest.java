package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import com.baomidou.mybatisplus.extension.conditions.update.LambdaUpdateChainWrapper;
import com.hmdp.entity.TokenAccount;
import com.hmdp.entity.TokenOrder;
import com.hmdp.entity.TokenQuotaRecord;
import com.hmdp.mapper.TokenQuotaRecordMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static com.hmdp.service.impl.FluentChainMocks.chainMock;

class TokenAccountServiceImplTest {
    private TokenAccountServiceImpl service;
    private TokenQuotaRecordMapper records;
    private LambdaQueryChainWrapper<TokenAccount> query;
    private LambdaUpdateChainWrapper<TokenAccount> update;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        service = spy(new TokenAccountServiceImpl());
        records = mock(TokenQuotaRecordMapper.class);
        query = chainMock(LambdaQueryChainWrapper.class);
        update = chainMock(LambdaUpdateChainWrapper.class);
        ReflectionTestUtils.setField(service, "quotaRecordMapper", records);
        doReturn(query).when(service).lambdaQuery();
        doReturn(update).when(service).lambdaUpdate();
        when(records.selectCount(any())).thenReturn(0L);
        when(records.insert(any(TokenQuotaRecord.class))).thenReturn(1);
    }

    @Test
    void newAccountHasZeroUsedAndReservedQuota() {
        doReturn(true).when(service).save(any(TokenAccount.class));

        service.grantFromPaidOrder(order(), 3L, 30);

        ArgumentCaptor<TokenAccount> saved = ArgumentCaptor.forClass(TokenAccount.class);
        verify(service).save(saved.capture());
        assertThat(saved.getValue().getTotalQuota()).isEqualTo(1000L);
        assertThat(saved.getValue().getUsedQuota()).isZero();
        assertThat(saved.getValue().getReservedQuota()).isZero();
    }

    @Test
    void purchasePreservesConsumedAndReservedQuotaAndRecordsAvailableBalance() {
        TokenAccount account = new TokenAccount().setId(4L).setUserId(7L).setModelId(3L)
                .setTotalQuota(5000L).setUsedQuota(900L).setReservedQuota(600L)
                .setExpireTime(LocalDateTime.now().plusDays(2)).setVersion(4);
        when(query.one()).thenReturn(account);
        when(update.update()).thenReturn(true);

        service.grantFromPaidOrder(order(), 3L, 30);

        ArgumentCaptor<TokenQuotaRecord> record = ArgumentCaptor.forClass(TokenQuotaRecord.class);
        verify(records).insert(record.capture());
        assertThat(record.getValue().getBalanceAfter()).isEqualTo(4500L);
        assertThat(account.getTotalQuota()).isEqualTo(6000L);
        assertThat(account.getUsedQuota()).isEqualTo(900L);
        assertThat(account.getReservedQuota()).isEqualTo(600L);
        verify(service, never()).save(any(TokenAccount.class));
    }

    @Test
    void concurrentGatewayChangeFailsPaymentForRetryWithoutWritingGrantRecord() {
        when(query.one()).thenReturn(new TokenAccount().setId(4L).setTotalQuota(5000L)
                .setUsedQuota(900L).setReservedQuota(600L).setVersion(4));
        when(update.update()).thenReturn(false);

        assertThatThrownBy(() -> service.grantFromPaidOrder(order(), 3L, 30))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("retry payment");

        verify(records, never()).insert(any(TokenQuotaRecord.class));
    }

    @Test
    void alreadyGrantedOrderDoesNotModifyAccount() {
        when(records.selectCount(any())).thenReturn(1L);

        service.grantFromPaidOrder(order(), 3L, 30);

        verifyNoInteractions(query, update);
        verify(records, never()).insert(any(TokenQuotaRecord.class));
    }

    private TokenOrder order() {
        return new TokenOrder().setId(12L).setUserId(7L).setPackageId(5L)
                .setQuotaAmount(1000L).setStatus(2);
    }
}
