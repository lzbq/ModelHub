package com.hmdp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * <p>
 * 
 * </p>
 *
 * @author 虎哥
 * @since 2021-12-22
 */
@Data
@EqualsAndHashCode(callSuper = false)//生成 equals 和 hashCode 方法，callSuper = false 表示不调用父类的 equals/hashCode
@Accessors(chain = true)//开启链式调用
@TableName("tb_user")//指定对应的数据库表名为 tb_user
public class User implements Serializable {

    private static final long serialVersionUID = 1L;//序列化版本号，保证序列化和反序列化的兼容性

    /**
     * 主键
     */
    //value = "id" - 对应数据库列名为 "id"
    //type = IdType.AUTO - 主键策略为数据库自增
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 手机号码
     */
    private String phone;

    /**
     * 密码，加密存储
     */
    private String password;

    /**
     * 昵称，默认是随机字符
     */
    private String nickName;

    /**
     * 用户头像
     */
    private String icon = "";

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;


}
