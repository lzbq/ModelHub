package com.hmdp.utils;

import com.hmdp.entity.TokenOrder;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.assertThat;

class TokenOrderSerializationTest {
    @Test
    void orderIdPreservesAllDigitsInBrowserJson() {
        long orderId = 630_234_567_890_123_456L;
        var json = JsonMapper.builder().build().valueToTree(new TokenOrder().setId(orderId));
        assertThat(json.get("id").isString()).isTrue();
        assertThat(json.get("id").asString()).isEqualTo(Long.toString(orderId));
    }
}
