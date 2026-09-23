package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.entity.TokenPackage;
import com.hmdp.service.ITokenPackageService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/admin/token-package")
public class AdminTokenPackageController {

    @Resource
    private ITokenPackageService tokenPackageService;

    @PostMapping("/seckill")
    public Result addSeckillPackage(@RequestBody TokenPackage tokenPackage) {
        return tokenPackageService.addSeckillPackage(tokenPackage);
    }
}
