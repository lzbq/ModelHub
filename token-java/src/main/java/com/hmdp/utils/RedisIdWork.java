package com.hmdp.utils;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

@Component
public class RedisIdWork {
    //开始时间戳
    private static final long BEGIN_TIMESTAMP = 1640995200L;
    //序列号位数
    private static final long COUNT_BITS = 32;
    @Autowired
    private StringRedisTemplate stringRedisTemplate;
    public long nextId(String keyPrefix) {
        //1.生成时间戳
        LocalDateTime now = LocalDateTime.now();
        long nowSecond = now.toEpochSecond(ZoneOffset.UTC);
        long timestamp = nowSecond - BEGIN_TIMESTAMP;
        //2.生成序列号--redis自增
        Long count = stringRedisTemplate.opsForValue().increment("icr:" + keyPrefix + ":" + now.format(DateTimeFormatter.ofPattern("yyyy:MM:dd")));
        //3.拼接并返回
        return timestamp << COUNT_BITS | count; //左移32位,或运算    31位时间戳+32位序列号
    }

}
