package com.hmdp.utils;

/** AI 模型多级缓存 Key。 */
public final class AiModelCacheKeys {

    public static final String MODEL_DETAIL_PREFIX = "cache:ai-model:";
    public static final String MODEL_DETAIL_LOCK_PREFIX = "lock:cache:ai-model:";
    public static final String HOT_LIST_PREFIX = "cache:ai-model:hot:";
    public static final String HOT_LIST_LOCK_PREFIX = "lock:cache:ai-model:hot:";
    public static final String HOT_LIST_VERSION = "cache:ai-model:hot:version";

    private AiModelCacheKeys() {
    }
}
