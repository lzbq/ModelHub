package com.hmdp.config;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.hmdp.entity.AiModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.time.Duration;
import java.util.List;

@Configuration
public class CaffeineConfig {

    @Bean
    public Cache<Long, AiModel> hotAiModelDetailLocalCache() {
        return Caffeine.newBuilder()
                .maximumSize(1_000)
                .expireAfterWrite(Duration.ofMinutes(1))
                .build();
    }

    @Bean
    public Cache<String, List<AiModel>> hotAiModelListLocalCache() {
        return Caffeine.newBuilder()
                .maximumSize(500)
                .expireAfterWrite(Duration.ofSeconds(15))
                .build();
    }
    //专门用于缓存刷新的线程池
    @Bean(name = "cacheRefreshExecutor")
    public ThreadPoolTaskExecutor cacheRefreshExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);//核心线程数是 2。平时最多保持 2 个线程常驻，用来处理缓存刷新任务。
        executor.setMaxPoolSize(4);//最大线程数是 4。任务多的时候，线程最多扩到 4 个。
        executor.setQueueCapacity(100);//任务队列容量是 100。
        executor.setThreadNamePrefix("cache-refresh-");//设置线程名前缀。
        executor.setWaitForTasksToCompleteOnShutdown(true);//应用关闭时，不是立刻杀掉线程池，而是等待已经提交的任务执行完。
        executor.setAwaitTerminationSeconds(10);//最多等 10 秒。
        executor.initialize();//初始化线程池。这个方法必须调用，否则线程池配置不会真正生效。
        return executor;
    }
}
