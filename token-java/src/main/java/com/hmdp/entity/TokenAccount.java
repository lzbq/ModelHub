package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("tb_token_account")
public class TokenAccount implements Serializable {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Long modelId;
    private Long totalQuota;
    private Long usedQuota;
    /** Quota held by in-flight or unresolved gateway requests. */
    private Long reservedQuota;
    private LocalDateTime expireTime;
    private Integer version;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
