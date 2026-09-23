package com.hmdp.utils;

/** ModelHub 登录态所需 Redis Key。业务 Key 在各领域服务内就近维护。 */
public final class RedisConstants {

    public static final String LOGIN_CODE_KEY = "login:code:";
    public static final Long LOGIN_CODE_TTL = 2L;
    public static final String LOGIN_USER_KEY = "login:token:";
    public static final Long LOGIN_USER_TTL = 600L;

    private RedisConstants() {
    }
}
