package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.dto.Result;
import com.hmdp.entity.TokenAccount;
import com.hmdp.entity.TokenOrder;
import com.hmdp.entity.TokenQuotaRecord;
import com.hmdp.mapper.TokenAccountMapper;
import com.hmdp.mapper.TokenQuotaRecordMapper;
import com.hmdp.service.ITokenAccountService;
import com.hmdp.utils.UserHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.annotation.Resource;
import java.time.LocalDateTime;

/*
* 用户 Token 额度账户服务，主要做两件事：
1.查询当前登录用户的 Token 账户。
2.用户订单支付成功后，给对应模型发放 Token 额度，并记录流水。
*
* 这个类负责维护用户购买 Token 后的账户余额：
* 支付成功后按模型给用户加额度、延长有效期、写额度流水，
* 并通过订单流水检查和乐观锁避免重复发放或并发覆盖。
* */
@Service
public class TokenAccountServiceImpl extends ServiceImpl<TokenAccountMapper, TokenAccount>
        implements ITokenAccountService {
    @Resource
    private TokenQuotaRecordMapper quotaRecordMapper;

    @Override
    public Result queryCurrentAccount(Long modelId) {
        Long userId = UserHolder.getUser().getId();
        return Result.ok(lambdaQuery().eq(TokenAccount::getUserId, userId)
                //如果传了 modelId，就只查某个模型的账户。如果没传 modelId，就查当前用户所有模型的账户。
                .eq(modelId != null, TokenAccount::getModelId, modelId).list());
    }

    @Override
    @Transactional
    public void grantFromPaidOrder(TokenOrder order, Long modelId, Integer validDays) {
        Long existing = quotaRecordMapper.selectCount(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<TokenQuotaRecord>()
                        .eq(TokenQuotaRecord::getOrderId, order.getId()));
        //如果这个订单已经有额度流水了，说明已经发放过，直接返回，防止重复加额度。
        if (existing > 0) {
            return;
        }
        //查用户在这个模型下是否已有账户
        TokenAccount account = lambdaQuery()
                .eq(TokenAccount::getUserId, order.getUserId())
                .eq(TokenAccount::getModelId, modelId)
                .one();
        LocalDateTime baseExpiry = LocalDateTime.now();
        //如果账户不存在，就新建账户。账户是按照userId + modelId区分的，用户购买不同模型的 Token，会进入不同账户。
        if (account == null) {
            account = new TokenAccount()
                    .setUserId(order.getUserId())
                    .setModelId(modelId)
                    .setTotalQuota(order.getQuotaAmount())
                    .setUsedQuota(0L)
                    .setReservedQuota(0L)
                    .setExpireTime(baseExpiry.plusDays(validDays == null ? 30 : validDays))
                    .setVersion(0);
            if (!save(account)) {
                throw new IllegalStateException("create token account failed; retry payment, orderId=" + order.getId());
            }
        } else {
            //如果账户已存在，就累加额度并延长有效期
            long newTotal = account.getTotalQuota() + order.getQuotaAmount();
            LocalDateTime currentExpiry = account.getExpireTime();
            //如果原账户还没过期，就从原过期时间继续往后延长。
            //如果原账户已经过期，就从现在开始重新计算有效期。
            LocalDateTime expiryBase = currentExpiry != null && currentExpiry.isAfter(baseExpiry) ? currentExpiry : baseExpiry;
            boolean updated = lambdaUpdate()
                    .set(TokenAccount::getTotalQuota, newTotal)
                    .set(TokenAccount::getExpireTime, expiryBase.plusDays(validDays == null ? 30 : validDays))
                    .setSql("version = version + 1")
                    .eq(TokenAccount::getId, account.getId())
                    //这里用了 version 做乐观锁。只有数据库里的 version 还等于查询出来的旧版本时，才允许更新。更新成功后 version + 1。防止同一订单重复充值
                    .eq(TokenAccount::getVersion, account.getVersion())
                    .update();
            if (!updated) {
                throw new IllegalStateException("grant token quota conflict; retry payment, orderId=" + order.getId());
            }
            account.setTotalQuota(newTotal);
        }
        //最后插入额度流水
        TokenQuotaRecord record = new TokenQuotaRecord()
                .setUserId(order.getUserId())
                .setModelId(modelId)
                .setOrderId(order.getId())
                .setChangeAmount(order.getQuotaAmount())//增加了多少额度
                .setChangeType("PURCHASE_GRANT")//变更类型是购买发放
                .setBalanceAfter(account.getTotalQuota()
                        - (account.getUsedQuota() == null ? 0L : account.getUsedQuota())
                        - (account.getReservedQuota() == null ? 0L : account.getReservedQuota()))//发放后的可用额度
                .setCreateTime(LocalDateTime.now());
        if (quotaRecordMapper.insert(record) != 1) {
            throw new IllegalStateException("write token quota grant failed; retry payment, orderId=" + order.getId());
        }
    }
}
