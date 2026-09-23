package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/** Token 额度审计流水。orderId 唯一，保证发放幂等。 */
@Data
@Accessors(chain = true)
@TableName("tb_token_quota_record")
public class TokenQuotaRecord implements Serializable {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Long modelId;
    private Long orderId;
    private Long changeAmount;
    private String changeType;
    private Long balanceAfter;
    private LocalDateTime createTime;
}
