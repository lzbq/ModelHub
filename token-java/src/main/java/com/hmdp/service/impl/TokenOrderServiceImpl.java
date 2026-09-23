package com.hmdp.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.dto.Result;
import com.hmdp.entity.AiModel;
import com.hmdp.entity.TokenOrder;
import com.hmdp.entity.TokenPackage;
import com.hmdp.mapper.TokenOrderMapper;
import com.hmdp.mapper.TokenPackageMapper;
import com.hmdp.mapper.AiModelMapper;
import com.hmdp.mq.TokenOrderProducer;
import com.hmdp.mq.TokenOrderTimeoutProducer;
import com.hmdp.service.ISeckillTokenPackageService;
import com.hmdp.service.AiModelPopularityService;
import com.hmdp.service.ITokenAccountService;
import com.hmdp.service.ITokenOrderService;
import com.hmdp.service.ITokenPackageService;
import com.hmdp.utils.RedisIdWork;
import com.hmdp.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Lazy;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.annotation.Resource;
import java.time.Duration;
import java.time.LocalDateTime;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static com.hmdp.service.impl.TokenPackageServiceImpl.TOKEN_STOCK_KEY;

/**
 * Token 套餐秒杀：Lua 原子预占 -> Redis Stream -> RocketMQ -> MySQL 订单
 * -> 支付后额度账本发放 -> 延迟消息取消未支付订单并补偿库存。
 */
@Slf4j
@Service
public class TokenOrderServiceImpl extends ServiceImpl<TokenOrderMapper, TokenOrder>
        implements ITokenOrderService {
    private static final String STREAM = "stream.token.orders";
    private static final String GROUP = "token-g1";
    private static final String CONSUMER = "token-c1";
    private static final String TOKEN_BUYER_KEY = "token:order:";
    private static final int UNPAID = 1;
    private static final int PAID = 2;
    private static final int CANCELED = 4;
    private static final ExecutorService DISPATCHER = Executors.newSingleThreadExecutor();
    private static final DefaultRedisScript<Long> SECKILL_SCRIPT = new DefaultRedisScript<>();
    private static final DefaultRedisScript<Long> RELEASE_SCRIPT = new DefaultRedisScript<>();

    static {
        SECKILL_SCRIPT.setLocation(new ClassPathResource("token_seckill.lua"));
        SECKILL_SCRIPT.setResultType(Long.class);
        RELEASE_SCRIPT.setLocation(new ClassPathResource("release_token_seckill.lua"));
        RELEASE_SCRIPT.setResultType(Long.class);
    }

    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private RedisIdWork redisIdWork;
    @Resource
    private RedissonClient redissonClient;
    @Resource
    private ISeckillTokenPackageService seckillPackageService;
    @Resource
    private ITokenPackageService tokenPackageService;
    @Resource
    private TokenPackageMapper tokenPackageMapper;
    @Resource
    private AiModelMapper aiModelMapper;
    @Resource
    private PlatformTransactionManager transactionManager;
    @Resource
    private ITokenAccountService tokenAccountService;
    @Resource
    private AiModelPopularityService aiModelPopularityService;
    @Resource
    private TokenOrderProducer orderProducer;
    @Resource
    private TokenOrderTimeoutProducer timeoutProducer;
    @Lazy
    @Resource
    private ITokenOrderService self;
    @Value("${modelhub.order.simulated-payment-enabled:false}")
    private boolean simulatedPaymentEnabled;
    @Value("${modelhub.order.timeout-seconds:1800}")
    private long timeoutSeconds = 1800;
    private volatile boolean running = true;

    @PostConstruct
    private void init() {
        ensureStreamGroup();
        running = true;
        DISPATCHER.submit(this::dispatchLoop);
    }

    /**
     * 创建 Stream 和消费组。MKSTREAM=true 保证首次部署时 Stream 不存在也能完成初始化；
     * 多实例并发启动时，后创建的实例会收到 BUSYGROUP，视为初始化成功。
     */
    private void ensureStreamGroup() {
        try {
            stringRedisTemplate.execute((RedisCallback<String>) connection ->
                    connection.streamCommands().xGroupCreate(
                            STREAM.getBytes(StandardCharsets.UTF_8),//Redis Stream 的 key
                            GROUP,//消费者组名称
                            ReadOffset.from("0"),//表示这个消费者组从 Stream 的起点开始消费。
                            true));
            log.info("created Redis Stream group: stream={}, group={}", STREAM, GROUP);
        } catch (RuntimeException ex) {
            if (!containsMessage(ex, "BUSYGROUP")) {
                throw ex;
            }
            log.info("Redis Stream group already exists: stream={}, group={}", STREAM, GROUP);
        }
    }

    private static boolean containsMessage(Throwable error, String keyword) {
        Throwable current = error;
        //Java 异常可能是多层包装的
        while (current != null) {
            if (current.getMessage() != null && current.getMessage().contains(keyword)) {
                //如果当前这一层异常信息不为空，并且包含目标关键字，就返回 true。
                //current.getMessage().contains(keyword)成立，说明这个异常链里有消费者组已存在的错误。
                return true;
            }
            current = current.getCause();//继续检查下一层原因异常。
        }
        return false;
    }

    @PreDestroy
    private void destroy() {
        running = false;
        DISPATCHER.shutdownNow();
    }

    private void dispatchLoop() {
        while (running) {
            try {
                List<MapRecord<String, Object, Object>> records = stringRedisTemplate.opsForStream().read(
                        Consumer.from(GROUP, CONSUMER),
                        StreamReadOptions.empty().count(1).block(Duration.ofSeconds(2)),
                        StreamOffset.create(STREAM, ReadOffset.lastConsumed()));
                if (records != null && !records.isEmpty()) {
                    dispatchAndAck(records.get(0));
                }
            } catch (Exception ex) {
                if (!running || Thread.currentThread().isInterrupted()) {
                    return;
                }
                log.error("dispatch token order failed", ex);
                handlePendingList();
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
    }

    private void handlePendingList() {
        while (running) {
            try {
                List<MapRecord<String, Object, Object>> records = stringRedisTemplate.opsForStream().read(
                        Consumer.from(GROUP, CONSUMER), StreamReadOptions.empty().count(1),
                        StreamOffset.create(STREAM, ReadOffset.from("0")));
                if (records == null || records.isEmpty()) {
                    return;
                }
                dispatchAndAck(records.get(0));
            } catch (Exception ex) {
                log.error("dispatch pending token order failed", ex);
                return;
            }
        }
    }

    private void dispatchAndAck(MapRecord<String, Object, Object> record) {
        Map<Object, Object> value = record.getValue();
        TokenOrder order = BeanUtil.fillBeanWithMap(value, new TokenOrder(), true);
        orderProducer.send(order);
        stringRedisTemplate.opsForStream().acknowledge(STREAM, GROUP, record.getId());
    }

    @Override
    public Result buyPackage(Long packageId) {
        Long userId = UserHolder.getUser().getId();
        RLock lock = redissonClient.getLock("lock:token-order:purchase:" + userId + ":" + packageId);
        if (!lock.tryLock()) {
            return Result.fail("package order is processing; retry shortly");
        }
        try {
            // TransactionTemplate commits before the lock is released, so concurrent retries
            // can observe and reuse the order that was just created.
            return new TransactionTemplate(transactionManager).execute(status -> {
                TokenPackage tokenPackage = tokenPackageService.getById(packageId);
                if (tokenPackage == null || !Integer.valueOf(0).equals(tokenPackage.getType())) {
                    return Result.fail("ordinary token package not found");
                }
                String unavailable = unavailableReason(tokenPackage);
                if (unavailable != null) {
                    return Result.fail(unavailable);
                }
                TokenOrder pending = lambdaQuery().eq(TokenOrder::getUserId, userId)
                        .eq(TokenOrder::getPackageId, packageId).eq(TokenOrder::getStatus, UNPAID)
                        .orderByDesc(TokenOrder::getCreateTime).last("LIMIT 1").one();
                if (pending != null && !isExpired(pending)) {
                    return Result.ok(pending.getId().toString());
                }
                if (pending != null) {
                    self.releaseTimeoutOrder(pending.getId());
                }
                TokenOrder order = new TokenOrder().setId(redisIdWork.nextId("token-order"))
                        .setUserId(userId).setPackageId(packageId).setQuotaAmount(tokenPackage.getTokenQuota())
                        .setStatus(UNPAID).setCreateTime(LocalDateTime.now());
                if (!save(order)) {
                    throw new IllegalStateException("save token order failed, orderId=" + order.getId());
                }
                afterCommit(() -> timeoutProducer.send(order.getId()));
                return Result.ok(order.getId().toString());
            });
        } finally {
            lock.unlock();
        }
    }

    private String unavailableReason(TokenPackage tokenPackage) {
        if (tokenPackage == null || !Integer.valueOf(1).equals(tokenPackage.getStatus())) {
            return "token package is unavailable";
        }
        if (tokenPackage.getTokenQuota() == null || tokenPackage.getTokenQuota() <= 0
                || tokenPackage.getPayValue() == null || tokenPackage.getPayValue() < 0
                || tokenPackage.getValidDays() == null || tokenPackage.getValidDays() <= 0) {
            return "token package configuration is invalid";
        }
        AiModel model = tokenPackage.getModelId() == null ? null : aiModelMapper.selectById(tokenPackage.getModelId());
        return model == null || !Integer.valueOf(1).equals(model.getStatus()) ? "model is unavailable" : null;
    }

    private boolean isExpired(TokenOrder order) {
        return order.getCreateTime() != null
                && !order.getCreateTime().plusSeconds(timeoutSeconds).isAfter(LocalDateTime.now());
    }

    @Override
    public Result seckillPackage(Long packageId) {
        TokenPackage tokenPackage = tokenPackageMapper.queryPackageDetail(packageId);
        if (tokenPackage == null || tokenPackage.getType() == null || tokenPackage.getType() != 1) {
            return Result.fail("seckill token package not found");
        }
        String unavailable = unavailableReason(tokenPackage);
        if (unavailable != null) {
            return Result.fail(unavailable);
        }

        LocalDateTime now = LocalDateTime.now();
        if (tokenPackage.getBeginTime() != null && now.isBefore(tokenPackage.getBeginTime())) {
            return Result.fail("sale not started");
        }
        if (tokenPackage.getEndTime() != null && now.isAfter(tokenPackage.getEndTime())) {
            return Result.fail("sale ended");
        }

        Long userId = UserHolder.getUser().getId();
        long orderId = redisIdWork.nextId("token-order");
        Long result = stringRedisTemplate.execute(SECKILL_SCRIPT, Collections.emptyList(),
                packageId.toString(), userId.toString(), String.valueOf(orderId));
        if (result == null) {
            return Result.fail("token package seckill failed");
        }
        if (result != 0) {
            return Result.fail(result == 1 ? "stock not enough" : "duplicate package order");
        }
        return Result.ok(Long.toString(orderId));
    }

    @Override
    public void handleSeckillOrder(TokenOrder order) {
        //订单创建消费者先按 userId 获取 Redisson 锁
        RLock lock = redissonClient.getLock("lock:token-order:" + order.getUserId());
        if (!lock.tryLock()) {
            throw new IllegalStateException("token order is processing, userId=" + order.getUserId());
        }
        try {
            self.createTokenOrder(order);
        } finally {
            lock.unlock();
        }
    }

    @Override
    @Transactional
    public void createTokenOrder(TokenOrder order) {
        //进入事务后根据 orderId 判断订单是否已存在，再判断该用户是否已有同一套餐的未取消订单。
        if (getById(order.getId()) != null) {
            return;
        }
        Long count = lambdaQuery().eq(TokenOrder::getUserId, order.getUserId())
                .eq(TokenOrder::getPackageId, order.getPackageId())
                .ne(TokenOrder::getStatus, CANCELED).count();
        if (count > 0) {
            releaseRedisState(order);
            return;
        }
        //下单创建订单时扣数据库库存
        boolean deducted = seckillPackageService.lambdaUpdate()
                .setSql("stock = stock - 1")
                .eq(com.hmdp.entity.SeckillTokenPackage::getPackageId, order.getPackageId())
                .gt(com.hmdp.entity.SeckillTokenPackage::getStock, 0)
                .update();
        if (!deducted) {
            releaseRedisState(order);
            return;
        }
        //
        TokenPackage tokenPackage = tokenPackageService.getById(order.getPackageId());
        if (tokenPackage == null) {
            throw new IllegalStateException("token package missing, packageId=" + order.getPackageId());
        }
        order.setQuotaAmount(tokenPackage.getTokenQuota()).setStatus(UNPAID);
        if (!save(order)) {
            throw new IllegalStateException("save token order failed, orderId=" + order.getId());
        }
        afterCommit(() -> timeoutProducer.send(order.getId()));
    }

    @Override
    @Transactional
    public Result payTokenOrder(Long orderId) {
        TokenOrder order = getById(orderId);
        if (order == null) {
            return Result.fail("token order not found");
        }
        //校验订单归属
        Long userId = UserHolder.getUser().getId();
        if (!userId.equals(order.getUserId())) {
            return Result.fail("order owner mismatch");
        }
        if (order.getStatus() != null && order.getStatus() == PAID) {
            return Result.ok(orderId.toString());
        }
        if (!simulatedPaymentEnabled) {
            return Result.fail("simulated payment is disabled; enable modelhub.order.simulated-payment-enabled only for local demos");
        }
        if (!Integer.valueOf(UNPAID).equals(order.getStatus())) {
            return Result.fail("order status cannot be paid");
        }
        if (isExpired(order)) {
            self.releaseTimeoutOrder(orderId);
            return Result.fail("order has expired");
        }
        TokenPackage tokenPackage = tokenPackageService.getById(order.getPackageId());
        String unavailable = unavailableReason(tokenPackage);
        if (unavailable != null) {
            return Result.fail(unavailable);
        }
        boolean paid = lambdaUpdate().set(TokenOrder::getStatus, PAID)
                .set(TokenOrder::getPayTime, LocalDateTime.now())
                .eq(TokenOrder::getId, orderId).eq(TokenOrder::getUserId, userId)
                .eq(TokenOrder::getStatus, UNPAID).update();
        if (!paid) {
            return Result.fail("order status cannot be paid");
        }
        order.setStatus(PAID);
        //在订单支付成功后调用，用来把套餐里的 Token 发到用户账户里。
        tokenAccountService.grantFromPaidOrder(order, tokenPackage.getModelId(), tokenPackage.getValidDays());
        //购买量只统计真正完成支付并提交成功的订单。
        afterCommit(() -> aiModelPopularityService.recordPurchase(tokenPackage.getModelId()));
        return Result.ok(orderId.toString());
    }

    @Override
    public Result queryOrder(Long orderId) {
        TokenOrder order = getById(orderId);
        if (order == null) {
            return Result.fail("token order not found");
        }
        return UserHolder.getUser().getId().equals(order.getUserId())
                ? Result.ok(order) : Result.fail("order owner mismatch");
    }

    @Override
    public Result queryCurrentOrders(Integer current) {
        int pageNo = current == null || current < 1 ? 1 : current;
        Page<TokenOrder> page = lambdaQuery().eq(TokenOrder::getUserId, UserHolder.getUser().getId())
                .orderByDesc(TokenOrder::getCreateTime).orderByDesc(TokenOrder::getId)
                .page(new Page<>(pageNo, 10));
        return Result.ok(page.getRecords(), page.getTotal());
    }

    @Override
    @Transactional
    public void releaseTimeoutOrder(Long orderId) {
        //超时取消消费者只处理待支付订单，已支付或已取消订单直接忽略。
        TokenOrder order = getById(orderId);
        if (order == null || order.getStatus() == null || order.getStatus() != UNPAID) {
            return;
        }
        boolean canceled = lambdaUpdate().set(TokenOrder::getStatus, CANCELED)
                .eq(TokenOrder::getId, orderId).eq(TokenOrder::getStatus, UNPAID).update();
        if (!canceled) {
            return;
        }
        TokenPackage tokenPackage = tokenPackageService.getById(order.getPackageId());
        if (tokenPackage == null) {
            throw new IllegalStateException("token package missing for order cancellation, orderId=" + orderId);
        }
        // 普通套餐没有秒杀库存或 Redis 预占状态，只取消订单。
        if (!Integer.valueOf(1).equals(tokenPackage.getType())) {
            return;
        }
        // 秒杀订单超时取消时恢复库存
        boolean released = seckillPackageService.lambdaUpdate().setSql("stock = stock + 1")
                .eq(com.hmdp.entity.SeckillTokenPackage::getPackageId, order.getPackageId()).update();
        if (!released) {
            throw new IllegalStateException("release token stock failed, orderId=" + orderId);
        }
        releaseRedisState(order);
    }

    private void releaseRedisState(TokenOrder order) {
        Long result = stringRedisTemplate.execute(RELEASE_SCRIPT,
                Arrays.asList(TOKEN_STOCK_KEY + order.getPackageId(), TOKEN_BUYER_KEY + order.getPackageId()),
                String.valueOf(order.getUserId()));
        if (result == null) {
            throw new IllegalStateException("release token redis state failed, orderId=" + order.getId());
        }
    }

    private static void afterCommit(Runnable action) {
        Runnable bestEffort = () -> {
            try {
                action.run();
            } catch (RuntimeException ex) {
                // The business transaction has already committed. Reporting an API failure here
                // invites duplicate purchases, so retain the successful result and log recovery work.
                log.error("token order committed but post-commit action failed; retry delayed-message/statistics delivery", ex);
            }
        };
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            bestEffort.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                bestEffort.run();
            }
        });
    }
}
