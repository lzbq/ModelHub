package com.hmdp.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.entity.TokenPackage;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

public interface TokenPackageMapper extends BaseMapper<TokenPackage> {
    @Select("""
            SELECT p.id, p.model_id, m.name AS model_name, p.title, p.sub_title, p.rules, p.token_quota,
                   p.pay_value, p.valid_days, p.type, p.status, p.create_time, p.update_time,
                   s.stock, s.begin_time, s.end_time
            FROM tb_token_package p
            LEFT JOIN tb_ai_model m ON m.id = p.model_id
            LEFT JOIN tb_seckill_token_package s ON p.id = s.package_id
            WHERE p.model_id = #{modelId} AND p.status = 1
            ORDER BY p.type DESC, p.pay_value ASC
            """)
    List<TokenPackage> queryByModelId(@Param("modelId") Long modelId);

    @Select("""
            SELECT p.id, p.model_id, m.name AS model_name, p.title, p.sub_title, p.rules, p.token_quota,
                   p.pay_value, p.valid_days, p.type, p.status, p.create_time, p.update_time,
                   s.stock, s.begin_time, s.end_time
            FROM tb_token_package p
            LEFT JOIN tb_ai_model m ON m.id = p.model_id
            LEFT JOIN tb_seckill_token_package s ON p.id = s.package_id
            WHERE p.id = #{packageId} AND p.status = 1
            """)
    TokenPackage queryPackageDetail(@Param("packageId") Long packageId);

    @Select("""
            SELECT p.id, p.model_id, m.name AS model_name, p.title, p.sub_title, p.rules, p.token_quota,
                   p.pay_value, p.valid_days, p.type, p.status, p.create_time, p.update_time,
                   s.stock, s.begin_time, s.end_time
            FROM tb_token_package p
            LEFT JOIN tb_ai_model m ON m.id = p.model_id
            LEFT JOIN tb_seckill_token_package s ON p.id = s.package_id
            WHERE p.status = 1
            ORDER BY p.type DESC, p.pay_value ASC
            """)
    IPage<TokenPackage> queryHot(Page<TokenPackage> page);
}
