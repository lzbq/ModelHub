package com.hmdp.gateway;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Data
@Component
@ConfigurationProperties(prefix = "modelhub.gateway")
public class GatewayProperties {
    private boolean enabled;
    private String baseUrl = "";
    private String apiKey = "";
    private int timeoutSeconds = 60;
    private int requestsPerMinute = 20;
    private int maxInputBytes = 16384;
    private int maxOutputTokens = 4096;
    private int maxResponseBytes = 1048576;
    private List<ModelMapping> models = new ArrayList<>();

    @Data
    public static class ModelMapping {
        private String alias;
        private Long modelId;
        private String upstreamModel = "";
    }
}
