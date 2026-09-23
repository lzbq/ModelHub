package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.dto.Result;
import com.hmdp.entity.SeckillTokenPackage;
import com.hmdp.entity.TokenPackage;
import com.hmdp.mapper.TokenPackageMapper;
import com.hmdp.service.ISeckillTokenPackageService;
import com.hmdp.service.ITokenPackageService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;

import jakarta.annotation.Resource;

@Service
public class TokenPackageServiceImpl extends ServiceImpl<TokenPackageMapper, TokenPackage>
        implements ITokenPackageService {
    public static final String TOKEN_STOCK_KEY = "token:stock:";

    @Resource
    private ISeckillTokenPackageService seckillTokenPackageService;
    @Resource
    private StringRedisTemplate stringRedisTemplate;

    /*
    * 根据 modelId 查询某个 AI 模型对应的 Token 套餐。
    * */
    @Override
    public Result queryByModelId(Long modelId) {
        return Result.ok(getBaseMapper().queryByModelId(modelId));
    }

    /*
    * 根据套餐 ID 查详情。
    * */
    @Override
    public Result queryDetail(Long packageId) {
        TokenPackage tokenPackage = getBaseMapper().queryPackageDetail(packageId);
        return tokenPackage == null ? Result.fail("token package not found") : Result.ok(tokenPackage);
    }

    @Override
    public Result queryHot(Integer current) {
        int pageNo = current == null || current < 1 ? 1 : current;
        Page<TokenPackage> page = new Page<>(pageNo, 10);
        getBaseMapper().queryHot(page);
        return Result.ok(page.getRecords(), page.getTotal());
    }

    @Override
    @Transactional
    public Result addSeckillPackage(TokenPackage tokenPackage) {
        Result validateResult = validateSeckillPackage(tokenPackage);
        if (!validateResult.getSuccess()) {
            return validateResult;
        }
        tokenPackage.setType(1);
        if (tokenPackage.getStatus() == null) {
            tokenPackage.setStatus(1);
        }
        save(tokenPackage);
        SeckillTokenPackage seckill = new SeckillTokenPackage()
                .setPackageId(tokenPackage.getId())
                .setStock(tokenPackage.getStock())
                .setBeginTime(tokenPackage.getBeginTime())
                .setEndTime(tokenPackage.getEndTime());
        seckillTokenPackageService.save(seckill);
        stringRedisTemplate.opsForValue().set(TOKEN_STOCK_KEY + tokenPackage.getId(), String.valueOf(tokenPackage.getStock()));
        return Result.ok(tokenPackage.getId());
    }

    private Result validateSeckillPackage(TokenPackage tokenPackage) {
        if (tokenPackage == null) {
            return Result.fail("token package is required");
        }
        if (tokenPackage.getModelId() == null || tokenPackage.getModelId() <= 0) {
            return Result.fail("modelId is required");
        }
        if (tokenPackage.getTitle() == null || tokenPackage.getTitle().trim().isEmpty()) {
            return Result.fail("title is required");
        }
        if (tokenPackage.getTokenQuota() == null || tokenPackage.getTokenQuota() <= 0) {
            return Result.fail("tokenQuota must be greater than 0");
        }
        if (tokenPackage.getPayValue() == null || tokenPackage.getPayValue() < 0) {
            return Result.fail("payValue must be greater than or equal to 0");
        }
        if (tokenPackage.getValidDays() == null || tokenPackage.getValidDays() <= 0) {
            return Result.fail("validDays must be greater than 0");
        }
        if (tokenPackage.getStock() == null || tokenPackage.getStock() <= 0) {
            return Result.fail("stock must be greater than 0");
        }
        if (tokenPackage.getBeginTime() == null) {
            return Result.fail("beginTime is required");
        }
        if (tokenPackage.getEndTime() == null) {
            return Result.fail("endTime is required");
        }
        if (!tokenPackage.getBeginTime().isBefore(tokenPackage.getEndTime())) {
            return Result.fail("beginTime must be before endTime");
        }
        return Result.ok();
    }
}
