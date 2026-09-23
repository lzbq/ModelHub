package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.service.ITokenPackageService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController
@RequestMapping("/token-package")
public class TokenPackageController {
    /*
    * 查询 Token 套餐详情、热门套餐和指定模型可购买的套餐。
    * */
    @Resource
    private ITokenPackageService tokenPackageService;

    @GetMapping("/{id}")
    public Result detail(@PathVariable Long id) {
        return tokenPackageService.queryDetail(id);
    }

    @GetMapping("/hot")
    public Result hot(@org.springframework.web.bind.annotation.RequestParam(defaultValue = "1") Integer current) {
        return tokenPackageService.queryHot(current);
    }

    @GetMapping("/model/{modelId}")
    public Result byModel(@PathVariable Long modelId) {
        return tokenPackageService.queryByModelId(modelId);
    }
}
