package com.hmdp.gateway;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static com.hmdp.gateway.GatewayTypes.*;
/*
* 1、模型别名映射
* 客户端传的是项目内别名，例如 modelhub-chat。
网关内部根据配置映射到数据库模型 ID 和真实上游模型 ID，例如百炼的 qwen3.5-flash。
这样客户端不直接依赖供应商模型命名，也便于以后换供应商。、
* 2、请求校验和输入限制
* 当前只支持非流式调用：stream=false。
只接受 system/user/assistant 纯文本消息。
限制消息数量、输入字节数、max_tokens、temperature、上下文窗口。
请求体最大 512 KB，防止大 body 在反序列化前压垮服务。
* */
@Service
public class GatewayService {
    private final GatewayProperties properties;
    private final JdbcTemplate jdbc;
    private final GatewayLedger ledger;
    private final GatewayRateLimiter limiter;
    private final GatewayUpstreamClient upstream;
    private final ObjectMapper json;

    public GatewayService(GatewayProperties properties, JdbcTemplate jdbc, GatewayLedger ledger,
                          GatewayRateLimiter limiter, GatewayUpstreamClient upstream, ObjectMapper json) {
        this.properties = properties;
        this.jdbc = jdbc;
        this.ledger = ledger;
        this.limiter = limiter;
        this.upstream = upstream;
        this.json = json;
    }

    private List<Model> catalog() {
        List<Model> result = new ArrayList<>();
        Set<String> seen = new java.util.HashSet<>();
        for (GatewayProperties.ModelMapping mapping : properties.getModels()) {
            if (mapping.getAlias() == null || !mapping.getAlias().matches("[A-Za-z0-9._/-]{1,100}")
                    || mapping.getModelId() == null || !seen.add(mapping.getAlias())) continue;
            result.addAll(jdbc.query("SELECT * FROM tb_ai_model WHERE id = ? AND status = 1 AND category IN ('chat', 'reasoning')",
                    (rs, n) -> new Model(mapping.getAlias(), rs.getLong("id"), rs.getString("name"), rs.getString("provider"),
                            mapping.getUpstreamModel(), rs.getLong("input_price"), rs.getLong("output_price"), rs.getInt("context_window")),
                    mapping.getModelId()));
        }
        return result;
    }

    public List<Map<String, Object>> models() {
        return catalog().stream().map(model -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", model.alias());
            row.put("modelId", model.modelId());
            row.put("name", model.name());
            row.put("provider", model.provider());
            row.put("configured", upstream.configured() && model.upstreamModel() != null && !model.upstreamModel().isBlank());
            return row;
        }).toList();
    }

    public Map<String, Object> apiModels() {
        List<Map<String, Object>> rows = models().stream().filter(row -> Boolean.TRUE.equals(row.get("configured")))
                .map(row -> Map.<String, Object>of("id", row.get("id"), "object", "model", "created", 0, "owned_by", row.get("provider")))
                .toList();
        return Map.of("object", "list", "data", rows);
    }

    public Completion complete(Identity identity, ChatRequest request, String idempotencyKey) {
        if (request == null || request.model() == null) throw invalid("请指定模型别名");
        Model model = catalog().stream().filter(item -> item.alias().equals(request.model())).findFirst()
                .orElseThrow(() -> new GatewayException(400, "model_not_available", "模型未上架或不支持聊天调用"));
        ValidatedRequest valid = validate(request, model);
        if (!upstream.configured() || model.upstreamModel() == null || model.upstreamModel().isBlank()) {
            throw new GatewayException(503, "gateway_not_configured", "模型网关尚未启用或配置上游，请联系管理员");
        }
        String key = idempotencyKey == null ? UUID.randomUUID().toString() : idempotencyKey;
        if (!key.matches("[A-Za-z0-9._:-]{1,100}")) throw invalid("Idempotency-Key 格式不正确");
        limiter.check(identity.principal());
        Reservation reservation = ledger.reserve(identity, key, valid.fingerprint(), model, valid.reservation());
        Entry entry = reservation.entry();
        if (!reservation.fresh()) {
            if ("SUCCEEDED".equals(entry.status()) && entry.responseJson() != null) {
                return new Completion(entry.requestId(), readMap(entry.responseJson()));
            }
            throw new GatewayException(409, "request_" + entry.status().toLowerCase(java.util.Locale.ROOT),
                    "该请求已存在，当前状态：" + entry.status() + "。请查询调用记录，勿更换幂等键自动重试。")
                    .withRequestId(entry.requestId());
        }
        try {
            GatewayUpstreamClient.Response response;
            try {
                response = upstream.send(json.writeValueAsString(valid.upstreamBody()));
            } catch (GatewayUpstreamClient.Failure failure) {
                if (failure.definitelyNotSent()) ledger.release(entry.requestId(), "upstream_connection_failed");
                else ledger.uncertain(entry.requestId(), "upstream_result_unknown");
                throw new GatewayException(502, failure.definitelyNotSent() ? "upstream_connection_failed" : "upstream_result_unknown",
                        failure.definitelyNotSent() ? "未能连接上游，预留额度已释放" : "上游响应未完整确认，额度已保留，等待对账");
            }
            ledger.providerRequestId(entry.requestId(), response.providerRequestId());
            if (response.status() < 200 || response.status() >= 300) {
                boolean rejected = Set.of(400, 401, 403, 404, 405, 413, 415, 422, 429).contains(response.status());
                if (rejected) ledger.release(entry.requestId(), "upstream_rejected_" + response.status());
                else ledger.uncertain(entry.requestId(), "upstream_status_" + response.status());
                throw new GatewayException(response.status() == 429 ? 429 : 502, "upstream_error",
                        rejected ? "上游拒绝本次请求，预留额度已释放" : "上游处理结果不确定，额度已保留，等待对账");
            }
            JsonNode body = json.readTree(response.body());
            Usage usage = usage(body);
            Map<String, Object> normalized = normalize(body, model, entry.requestId(), usage);
            if (response.providerRequestId() == null && body.path("id").isTextual()) {
                ledger.providerRequestId(entry.requestId(), body.path("id").asText());
            }
            if (!ledger.settle(entry.requestId(), usage, json.writeValueAsString(normalized))) {
                throw new GatewayException(502, "settlement_pending", "真实用量已记录，结算需人工核对，预留额度保持冻结");
            }
            return new Completion(entry.requestId(), normalized);
        } catch (GatewayException e) {
            ledger.uncertain(entry.requestId(), e.code());
            throw e.withRequestId(entry.requestId());
        } catch (RuntimeException e) {
            ledger.uncertain(entry.requestId(), "upstream_response_or_settlement_error");
            throw new GatewayException(502, "upstream_response_or_settlement_error", "响应或结算未完整确认，预留额度已保留，等待对账")
                    .withRequestId(entry.requestId());
        }
    }

    ValidatedRequest validate(ChatRequest request, Model model) {
        if (Boolean.TRUE.equals(request.stream())) {
            throw new GatewayException(400, "stream_not_supported", "当前网关只支持非流式调用，请设置 stream=false");
        }
        if (request.messages() == null || request.messages().isEmpty() || request.messages().size() > 64) {
            throw invalid("messages 需包含 1 到 64 条文本消息");
        }
        long bytes = 0;
        for (Message message : request.messages()) {
            if (message == null || message.role() == null || !Set.of("system", "user", "assistant").contains(message.role())
                    || message.content() == null) throw invalid("仅支持 system、user、assistant 的纯文本消息");
            bytes += message.content().getBytes(StandardCharsets.UTF_8).length;
        }
        if (bytes == 0 || bytes > Math.min(262144, Math.max(1, properties.getMaxInputBytes()))) {
            throw invalid("输入为空或超过网关输入长度限制");
        }
        int max = request.max_tokens() == null ? Math.min(1024, properties.getMaxOutputTokens()) : request.max_tokens();
        if (max < 1 || max > Math.min(32768, Math.max(1, properties.getMaxOutputTokens()))) {
            throw invalid("max_tokens 超出允许范围");
        }
        double temperature = request.temperature() == null ? 1.0 : request.temperature();
        if (!Double.isFinite(temperature) || temperature < 0 || temperature > 2) throw invalid("temperature 需在 0 到 2 之间");
        // A deliberately conservative estimate, not an assertion of actual model tokenization.
        // Actual usage may exceed it; settlement then checks available quota atomically or retains the hold.
        long reserve = bytes + request.messages().size() * 64L + 128 + max;
        if (model.contextWindow() > 0 && reserve > model.contextWindow()) throw invalid("输入与输出预算超过模型上下文限制");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("model", model.upstreamModel());
        payload.put("messages", request.messages());
        payload.put("max_tokens", max);
        payload.put("temperature", temperature);
        payload.put("stream", false);
        return new ValidatedRequest(payload, GatewayKeyService.hash(request.model() + "\n" + json.writeValueAsString(payload)), reserve);
    }

    Usage usage(JsonNode body) {
        JsonNode usage = body.path("usage");
        JsonNode input = usage.path("prompt_tokens");
        JsonNode output = usage.path("completion_tokens");
        if (!input.isIntegralNumber() || !output.isIntegralNumber() || !input.canConvertToLong() || !output.canConvertToLong()) {
            throw new GatewayException(502, "upstream_usage_missing", "上游未返回有效 Token 用量，额度已保留，等待对账");
        }
        long prompt = input.asLong();
        long completion = output.asLong();
        if (prompt < 0 || completion < 0 || prompt > 10000000 || completion > 10000000 || prompt + completion == 0) {
            throw new GatewayException(502, "upstream_usage_invalid", "上游 Token 用量异常，额度已保留，等待对账");
        }
        JsonNode total = usage.path("total_tokens");
        if (!total.isMissingNode() && (!total.isIntegralNumber() || !total.canConvertToLong() || total.asLong() != prompt + completion)) {
            throw new GatewayException(502, "upstream_usage_invalid", "上游 Token 用量不一致，额度已保留，等待对账");
        }
        return new Usage(prompt, completion);
    }

    private Map<String, Object> normalize(JsonNode body, Model model, String requestId, Usage usage) {
        JsonNode choices = body.path("choices");
        if (!choices.isArray() || choices.isEmpty()) throw new GatewayException(502, "upstream_response_invalid", "上游未返回有效回答");
        List<Map<String, Object>> clean = new ArrayList<>();
        for (JsonNode choice : choices) {
            JsonNode message = choice.path("message");
            JsonNode content = message.path("content");
            if (!"assistant".equals(message.path("role").asText()) || !content.isTextual()) {
                throw new GatewayException(502, "upstream_response_invalid", "上游返回了不支持的回答格式");
            }
            Map<String, Object> outputMessage = new LinkedHashMap<>();
            outputMessage.put("role", "assistant");
            outputMessage.put("content", content.asText());
            Map<String, Object> outputChoice = new LinkedHashMap<>();
            outputChoice.put("index", clean.size());
            outputChoice.put("message", outputMessage);
            outputChoice.put("finish_reason", choice.path("finish_reason").isTextual() ? choice.path("finish_reason").asText() : "stop");
            clean.add(outputChoice);
        }
        return Map.of("id", "chatcmpl-" + requestId, "object", "chat.completion", "created", java.time.Instant.now().getEpochSecond(),
                "model", model.alias(), "choices", clean,
                "usage", Map.of("prompt_tokens", usage.promptTokens(), "completion_tokens", usage.completionTokens(), "total_tokens", usage.totalTokens()));
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readMap(String value) { return json.readValue(value, Map.class); }
    private GatewayException invalid(String message) { return new GatewayException(400, "invalid_request_error", message); }
}
