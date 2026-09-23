package com.hmdp.gateway;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public final class GatewayTypes {
    private GatewayTypes() {}

    public record Message(String role, String content) {}
    public record ChatRequest(String model, List<Message> messages, Integer max_tokens,
                              Double temperature, Boolean stream) {}
    public record Identity(long userId, String principal, String keyId) {}
    public record Model(String alias, long modelId, String name, String provider,
                        String upstreamModel, long inputPrice, long outputPrice, int contextWindow) {}
    public record ValidatedRequest(Map<String, Object> upstreamBody, String fingerprint, long reservation) {}
    public record Usage(long promptTokens, long completionTokens) {
        public long totalTokens() { return Math.addExact(promptTokens, completionTokens); }
        public BigDecimal costYuan(long inputPrice, long outputPrice) {
            return BigDecimal.valueOf(promptTokens).multiply(BigDecimal.valueOf(inputPrice))
                    .add(BigDecimal.valueOf(completionTokens).multiply(BigDecimal.valueOf(outputPrice)))
                    .movePointLeft(8);
        }
    }
    public record Entry(String requestId, long userId, long modelId, String model, String fingerprint,
                        long reservedTokens, String status, String responseJson, String errorCode,
                        long inputPrice, long outputPrice) {}
    public record Reservation(Entry entry, boolean fresh) {}
    public record Completion(String requestId, Map<String, Object> response) {}
}
