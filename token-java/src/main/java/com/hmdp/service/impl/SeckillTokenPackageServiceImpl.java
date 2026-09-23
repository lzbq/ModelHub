package com.hmdp.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.entity.SeckillTokenPackage;
import com.hmdp.mapper.SeckillTokenPackageMapper;
import com.hmdp.service.ISeckillTokenPackageService;
import org.springframework.stereotype.Service;
/*
* 是把 tb_seckill_token_package 表包装成一个 Spring Service，并继承 MyBatis-Plus 的通用 CRUD 能力。
* */
@Service
public class SeckillTokenPackageServiceImpl extends ServiceImpl<SeckillTokenPackageMapper, SeckillTokenPackage>
        implements ISeckillTokenPackageService {
}
