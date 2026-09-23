package com.hmdp.utils;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.Map;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class RefreshTokenInterceptorTest {
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final HashOperations<String, Object, Object> hashes = mock(HashOperations.class);
    private final RefreshTokenInterceptor interceptor = new RefreshTokenInterceptor();

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(interceptor, "stringRedisTemplate", redis);
        when(redis.opsForHash()).thenReturn(hashes);
        UserHolder.removeUser();
    }

    @AfterEach
    void clearUser() { UserHolder.removeUser(); }

    @Test
    void acceptsBearerSessionAndCleansRequestIdentity() throws Exception {
        var request = new MockHttpServletRequest();
        request.addHeader("Authorization", "Bearer browser-session");
        when(hashes.entries(RedisConstants.LOGIN_USER_KEY + "browser-session"))
                .thenReturn(Map.of("id", "7", "nickName", "开发者"));
        assertThat(interceptor.preHandle(request, new MockHttpServletResponse(), new Object())).isTrue();
        assertThat(UserHolder.getUser().getId()).isEqualTo(7L);
        interceptor.afterCompletion(request, new MockHttpServletResponse(), new Object(), null);
        assertThat(UserHolder.getUser()).isNull();
    }

    @Test
    void keepsExistingRawTokenClientsWorking() throws Exception {
        var request = new MockHttpServletRequest();
        request.addHeader("authorization", "legacy-session");
        when(hashes.entries(RedisConstants.LOGIN_USER_KEY + "legacy-session"))
                .thenReturn(Map.of("id", "8"));
        interceptor.preHandle(request, new MockHttpServletResponse(), new Object());
        assertThat(UserHolder.getUser().getId()).isEqualTo(8L);
    }

    @Test
    void emptyBearerDoesNotLookUpAnEmptySession() throws Exception {
        var request = new MockHttpServletRequest();
        request.addHeader("authorization", "Bearer ");
        interceptor.preHandle(request, new MockHttpServletResponse(), new Object());
        assertThat(UserHolder.getUser()).isNull();
        verifyNoInteractions(hashes);
    }
}
