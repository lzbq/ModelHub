package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/** 大模型商品目录。价格单位为人民币分/百万 Token。 */
@Data
@Accessors(chain = true)
@TableName("tb_ai_model")
public class AiModel implements Serializable {
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private String provider;
    private String name;
    private String category;
    private String description;
    private Integer contextWindow;
    private Long inputPrice;
    private Long outputPrice;
    private Integer status;
    private Long hotScore;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
