package com.hmdp.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmdp.dto.Result;
import com.hmdp.entity.TokenPackage;

public interface ITokenPackageService extends IService<TokenPackage> {
    Result queryByModelId(Long modelId);
    Result queryDetail(Long packageId);
    Result queryHot(Integer current);
    Result addSeckillPackage(TokenPackage tokenPackage);
}
