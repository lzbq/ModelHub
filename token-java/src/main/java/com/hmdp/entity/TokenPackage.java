package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/** 可购买的 Token 额度套餐。payValue 单位为分，tokenQuota 为套餐额度。 */
@Data
@Accessors(chain = true)
@TableName("tb_token_package")
public class TokenPackage implements Serializable {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private Long modelId;
    @TableField(exist = false)
    private String modelName;
    private String title;
    private String subTitle;
    private String rules;
    private Long tokenQuota;
    private Long payValue;
    private Integer validDays;
    private Integer type;
    private Integer status;
    @TableField(exist = false)
    private Integer stock;
    @TableField(exist = false)
    private LocalDateTime beginTime;
    @TableField(exist = false)
    private LocalDateTime endTime;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
