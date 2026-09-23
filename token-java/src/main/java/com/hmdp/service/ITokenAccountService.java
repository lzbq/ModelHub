package com.hmdp.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmdp.dto.Result;
import com.hmdp.entity.TokenAccount;
import com.hmdp.entity.TokenOrder;

public interface ITokenAccountService extends IService<TokenAccount> {
    Result queryCurrentAccount(Long modelId);
    void grantFromPaidOrder(TokenOrder order, Long modelId, Integer validDays);
}
