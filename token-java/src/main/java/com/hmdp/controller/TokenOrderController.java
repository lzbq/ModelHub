package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.service.ITokenAccountService;
import com.hmdp.service.ITokenOrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController
@RequestMapping("/token-order")
public class TokenOrderController {
    /*
    * 普通购买、秒杀下单、模拟支付、查询本人订单和 Token 额度账户。
    * */
    @Resource
    private ITokenOrderService tokenOrderService;
    @Resource
    private ITokenAccountService tokenAccountService;

    @PostMapping("/create/{packageId}")
    public Result create(@PathVariable Long packageId) {
        return tokenOrderService.buyPackage(packageId);
    }

    @PostMapping("/seckill/{packageId}")
    public Result seckill(@PathVariable Long packageId) {
        return tokenOrderService.seckillPackage(packageId);
    }

    @PostMapping("/pay/{orderId}")
    public Result pay(@PathVariable Long orderId) {
        return tokenOrderService.payTokenOrder(orderId);
    }

    @GetMapping("/{orderId}")
    public Result order(@PathVariable Long orderId) {
        return tokenOrderService.queryOrder(orderId);
    }

    @GetMapping("/me")
    public Result myOrders(@RequestParam(defaultValue = "1") Integer current) {
        return tokenOrderService.queryCurrentOrders(current);
    }

    @GetMapping("/account/me")
    public Result account(@RequestParam(required = false) Long modelId) {
        return tokenAccountService.queryCurrentAccount(modelId);
    }
}
