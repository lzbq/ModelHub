package com.hmdp.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmdp.dto.Result;
import com.hmdp.entity.TokenOrder;

public interface ITokenOrderService extends IService<TokenOrder> {
    Result buyPackage(Long packageId);
    Result seckillPackage(Long packageId);
    Result payTokenOrder(Long orderId);
    Result queryOrder(Long orderId);
    Result queryCurrentOrders(Integer current);
    void handleSeckillOrder(TokenOrder tokenOrder);
    void createTokenOrder(TokenOrder tokenOrder);
    void releaseTimeoutOrder(Long orderId);
}
