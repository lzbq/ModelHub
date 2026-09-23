package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.conditions.query.LambdaQueryChainWrapper;
import com.baomidou.mybatisplus.extension.conditions.update.LambdaUpdateChainWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.dto.Result;
import com.hmdp.dto.UserDTO;
import com.hmdp.entity.AiModel;
import com.hmdp.entity.SeckillTokenPackage;
import com.hmdp.entity.TokenOrder;
import com.hmdp.entity.TokenPackage;
import com.hmdp.mapper.AiModelMapper;
import com.hmdp.mq.TokenOrderTimeoutProducer;
import com.hmdp.service.AiModelPopularityService;
import com.hmdp.service.ISeckillTokenPackageService;
import com.hmdp.service.ITokenAccountService;
import com.hmdp.service.ITokenOrderService;
import com.hmdp.service.ITokenPackageService;
import com.hmdp.utils.RedisIdWork;
import com.hmdp.utils.UserHolder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static com.hmdp.service.impl.FluentChainMocks.chainMock;

class TokenOrderServiceImplTest {
    private static final long ORDER_ID = 9007199254740993L;
    private TokenOrderServiceImpl service;
    private ITokenPackageService packages;
    private AiModelMapper models;
    private ITokenAccountService accounts;
    private ISeckillTokenPackageService seckill;
    private AiModelPopularityService popularity;
    private ITokenOrderService self;
    private TokenOrderTimeoutProducer timeouts;
    private RedisIdWork ids;
    private RedissonClient redisson;
    private RLock lock;
    private PlatformTransactionManager transactions;
    private StringRedisTemplate redis;
    private LambdaQueryChainWrapper<TokenOrder> query;
    private LambdaUpdateChainWrapper<TokenOrder> update;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        service = spy(new TokenOrderServiceImpl());
        packages = mock(ITokenPackageService.class);
        models = mock(AiModelMapper.class);
        accounts = mock(ITokenAccountService.class);
        seckill = mock(ISeckillTokenPackageService.class);
        popularity = mock(AiModelPopularityService.class);
        self = mock(ITokenOrderService.class);
        timeouts = mock(TokenOrderTimeoutProducer.class);
        ids = mock(RedisIdWork.class);
        redisson = mock(RedissonClient.class);
        lock = mock(RLock.class);
        transactions = mock(PlatformTransactionManager.class);
        redis = mock(StringRedisTemplate.class);
        query = chainMock(LambdaQueryChainWrapper.class);
        update = chainMock(LambdaUpdateChainWrapper.class);
        ReflectionTestUtils.setField(service, "tokenPackageService", packages);
        ReflectionTestUtils.setField(service, "aiModelMapper", models);
        ReflectionTestUtils.setField(service, "tokenAccountService", accounts);
        ReflectionTestUtils.setField(service, "seckillPackageService", seckill);
        ReflectionTestUtils.setField(service, "aiModelPopularityService", popularity);
        ReflectionTestUtils.setField(service, "self", self);
        ReflectionTestUtils.setField(service, "timeoutProducer", timeouts);
        ReflectionTestUtils.setField(service, "redisIdWork", ids);
        ReflectionTestUtils.setField(service, "redissonClient", redisson);
        ReflectionTestUtils.setField(service, "transactionManager", transactions);
        ReflectionTestUtils.setField(service, "stringRedisTemplate", redis);
        doReturn(query).when(service).lambdaQuery();
        doReturn(update).when(service).lambdaUpdate();
        when(redisson.getLock(anyString())).thenReturn(lock);
        when(lock.tryLock()).thenReturn(true);
        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(ids.nextId("token-order")).thenReturn(ORDER_ID);
        UserDTO user = new UserDTO();
        user.setId(7L);
        UserHolder.saveUser(user);
    }

    @AfterEach
    void tearDown() {
        UserHolder.removeUser();
    }

    @Test
    void ordinaryPurchaseUsesServerQuotaAndCommitsBeforeUnlock() {
        availablePackage();
        doReturn(true).when(service).save(any(TokenOrder.class));

        Result result = service.buyPackage(5L);

        assertThat(result.getData()).isEqualTo(Long.toString(ORDER_ID));
        ArgumentCaptor<TokenOrder> saved = ArgumentCaptor.forClass(TokenOrder.class);
        verify(service).save(saved.capture());
        assertThat(saved.getValue().getUserId()).isEqualTo(7L);
        assertThat(saved.getValue().getPackageId()).isEqualTo(5L);
        assertThat(saved.getValue().getQuotaAmount()).isEqualTo(10000L);
        assertThat(saved.getValue().getStatus()).isEqualTo(1);
        InOrder commitOrder = inOrder(transactions, lock);
        commitOrder.verify(transactions).commit(any());
        commitOrder.verify(lock).unlock();
        verify(timeouts).send(ORDER_ID);
        verifyNoInteractions(seckill, redis, accounts);
    }

    @Test
    void repeatedPurchaseReusesPendingOrder() {
        availablePackage();
        when(query.one()).thenReturn(order(1));

        assertThat(service.buyPackage(5L).getData()).isEqualTo(Long.toString(ORDER_ID));

        verify(service, never()).save(any(TokenOrder.class));
        verifyNoInteractions(ids, timeouts, accounts);
    }

    @Test
    void unavailablePackageAndSeckillPackageCannotUseOrdinaryPurchase() {
        when(packages.getById(5L)).thenReturn(tokenPackage().setStatus(0));
        assertThat(service.buyPackage(5L).getErrorMsg()).contains("unavailable");
        when(packages.getById(5L)).thenReturn(tokenPackage().setType(1));
        assertThat(service.buyPackage(5L).getErrorMsg()).contains("ordinary");
        verify(service, never()).save(any(TokenOrder.class));
        verifyNoInteractions(ids, models);
    }

    @Test
    void offlineModelCannotBePurchased() {
        availablePackage();
        when(models.selectById(3L)).thenReturn(new AiModel().setId(3L).setStatus(0));

        assertThat(service.buyPackage(5L).getErrorMsg()).isEqualTo("model is unavailable");
        verify(service, never()).save(any(TokenOrder.class));
    }

    @Test
    void timeoutDeliveryFailureDoesNotReportCommittedPurchaseAsFailure() {
        availablePackage();
        doReturn(true).when(service).save(any(TokenOrder.class));
        doThrow(new IllegalStateException("MQ unavailable")).when(timeouts).send(ORDER_ID);

        assertThat(service.buyPackage(5L).getSuccess()).isTrue();
        verify(transactions).commit(any());
        verify(lock).unlock();
    }

    @Test
    void simulatedPaymentIsDisabledByDefaultWithoutGrantingQuota() {
        doReturn(order(1)).when(service).getById(ORDER_ID);

        assertThat(service.payTokenOrder(ORDER_ID).getErrorMsg()).contains("simulated payment is disabled");

        verifyNoInteractions(accounts, packages, popularity, update);
    }

    @Test
    void alreadyPaidOrderIsIdempotentEvenWhenSimulationDisabled() {
        doReturn(order(2)).when(service).getById(ORDER_ID);

        assertThat(service.payTokenOrder(ORDER_ID).getData()).isEqualTo(Long.toString(ORDER_ID));
        verifyNoInteractions(accounts, update, popularity);
    }

    @Test
    void anotherUsersOrderCannotBeReadOrPaid() {
        doReturn(order(1).setUserId(8L)).when(service).getById(ORDER_ID);
        ReflectionTestUtils.setField(service, "simulatedPaymentEnabled", true);

        assertThat(service.queryOrder(ORDER_ID).getSuccess()).isFalse();
        assertThat(service.payTokenOrder(ORDER_ID).getSuccess()).isFalse();
        verifyNoInteractions(accounts, packages, update);
    }

    @Test
    void paymentValidatesPackageAndOnlyGrantsAfterStatusTransition() {
        ReflectionTestUtils.setField(service, "simulatedPaymentEnabled", true);
        doReturn(order(1)).when(service).getById(ORDER_ID);
        when(packages.getById(5L)).thenReturn(tokenPackage().setStatus(0));
        assertThat(service.payTokenOrder(ORDER_ID).getErrorMsg()).contains("unavailable");
        verifyNoInteractions(update, accounts);
        availablePackage();
        when(update.update()).thenReturn(false);
        assertThat(service.payTokenOrder(ORDER_ID).getSuccess()).isFalse();
        verifyNoInteractions(accounts);
        when(update.update()).thenReturn(true);

        assertThat(service.payTokenOrder(ORDER_ID).getSuccess()).isTrue();
        verify(accounts).grantFromPaidOrder(any(TokenOrder.class), eq(3L), eq(30));
    }

    @Test
    void expiredOrderCannotBePaidEvenWhenTimeoutMessageIsMissing() {
        ReflectionTestUtils.setField(service, "simulatedPaymentEnabled", true);
        doReturn(order(1).setCreateTime(LocalDateTime.now().minusHours(1)))
                .when(service).getById(ORDER_ID);

        assertThat(service.payTokenOrder(ORDER_ID).getErrorMsg()).contains("expired");
        verify(self).releaseTimeoutOrder(ORDER_ID);
        verifyNoInteractions(accounts, packages, update);
    }

    @Test
    void ordinaryTimeoutOnlyCancelsOrder() {
        doReturn(order(1)).when(service).getById(ORDER_ID);
        when(update.update()).thenReturn(true);
        when(packages.getById(5L)).thenReturn(tokenPackage());

        service.releaseTimeoutOrder(ORDER_ID);

        verify(update).update();
        verifyNoInteractions(seckill, redis, accounts);
    }

    @Test
    @SuppressWarnings("unchecked")
    void seckillTimeoutRestoresDatabaseAndRedisStock() {
        doReturn(order(1)).when(service).getById(ORDER_ID);
        when(update.update()).thenReturn(true);
        when(packages.getById(5L)).thenReturn(tokenPackage().setType(1));
        LambdaUpdateChainWrapper<SeckillTokenPackage> stockUpdate = chainMock(LambdaUpdateChainWrapper.class);
        when(seckill.lambdaUpdate()).thenReturn(stockUpdate);
        when(stockUpdate.update()).thenReturn(true);
        when(redis.execute(any(RedisScript.class), anyList(), any(Object[].class))).thenReturn(1L);

        service.releaseTimeoutOrder(ORDER_ID);

        verify(stockUpdate).setSql("stock = stock + 1");
        verify(stockUpdate).update();
        verify(redis).execute(any(RedisScript.class), eq(List.of("token:stock:5", "token:order:5")), eq("7"));
    }

    @Test
    void alreadyPaidOrConcurrentlyPaidOrderDoesNotReleaseStock() {
        doReturn(order(2)).when(service).getById(ORDER_ID);
        service.releaseTimeoutOrder(ORDER_ID);
        verifyNoInteractions(update, seckill, redis);
        doReturn(order(1)).when(service).getById(ORDER_ID);
        when(update.update()).thenReturn(false);
        service.releaseTimeoutOrder(ORDER_ID);
        verifyNoInteractions(seckill, redis, packages);
    }

    @Test
    @SuppressWarnings("unchecked")
    void currentOrdersUseFixedPageSizeAndReturnTotal() {
        Page<TokenOrder> page = new Page<>(1, 10);
        page.setRecords(List.of(order(1)));
        page.setTotal(21);
        when(query.page(any(Page.class))).thenReturn(page);

        Result result = service.queryCurrentOrders(1);

        assertThat(result.getTotal()).isEqualTo(21L);
        assertThat(result.getData()).isEqualTo(page.getRecords());
        verify(query).eq(any(), eq(7L));
        ArgumentCaptor<Page<TokenOrder>> captured = ArgumentCaptor.forClass(Page.class);
        verify(query).page(captured.capture());
        assertThat(captured.getValue().getSize()).isEqualTo(10);
    }

    private void availablePackage() {
        when(packages.getById(5L)).thenReturn(tokenPackage());
        when(models.selectById(3L)).thenReturn(new AiModel().setId(3L).setStatus(1));
    }

    private TokenPackage tokenPackage() {
        return new TokenPackage().setId(5L).setModelId(3L).setType(0).setStatus(1)
                .setTokenQuota(10000L).setPayValue(100L).setValidDays(30);
    }

    private TokenOrder order(int status) {
        return new TokenOrder().setId(ORDER_ID).setUserId(7L).setPackageId(5L)
                .setQuotaAmount(10000L).setStatus(status).setCreateTime(LocalDateTime.now());
    }
}
