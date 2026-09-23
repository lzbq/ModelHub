package com.hmdp.config;

import com.hmdp.utils.LoginInterceptor;
import com.hmdp.utils.RefreshTokenInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import jakarta.annotation.Resource;

@Configuration
public class MvcConfig implements WebMvcConfigurer {

    @Resource
    private RefreshTokenInterceptor refreshTokenInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new LoginInterceptor())
                .excludePathPatterns(
                        "/ai-model/**",
                        "/token-package/**",
                        "/user/code",
                        "/user/login",
                        "/gateway/models",
                        "/v1/**",
                        "/error"
                )
                .order(1);
        // Platform API keys have their own authentication in the model gateway.
        registry.addInterceptor(refreshTokenInterceptor)
                .excludePathPatterns("/v1/**").order(0);
    }
}
