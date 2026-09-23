package com.hmdp.gateway;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;

import static com.hmdp.gateway.GatewayTypes.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class GatewayServiceTest {
    private GatewayProperties properties;
    private GatewayService service;
    private GatewayLedger ledger;
    private GatewayRateLimiter limiter;
    private GatewayUpstreamClient upstream;
    private final Model model = new Model("modelhub-chat", 1, "Test", "Provider",
            "provider-model", 100, 400, 128000);

    @BeforeEach
    void setUp() {
        properties = new GatewayProperties();
        var mapping = new GatewayProperties.ModelMapping();
        mapping.setAlias("modelhub-chat");
        mapping.setModelId(1L);
        mapping.setUpstreamModel("provider-model");
        properties.setModels(List.of(mapping));
        var db = new GatewayTestDatabase();
        ledger = mock(GatewayLedger.class);
        limiter = mock(GatewayRateLimiter.class);
        upstream = mock(GatewayUpstreamClient.class);
        service = new GatewayService(properties, db.jdbc, ledger, limiter, upstream, JsonMapper.builder().build());
    }

    @Test
    void validatedPayloadUsesTheServerSideProviderModelAndStableFingerprint() {
        ChatRequest request = new ChatRequest("modelhub-chat",
                List.of(new Message("system", "简洁回答"), new Message("user", "你好")), 256, 0.3, false);

        ValidatedRequest first = service.validate(request, model);
        ValidatedRequest second = service.validate(request, model);

        assertThat(first.upstreamBody()).containsEntry("model", "provider-model")
                .containsEntry("stream", false).containsEntry("max_tokens", 256);
        assertThat(first.fingerprint()).hasSize(64).isEqualTo(second.fingerprint());
        assertThat(first.reservation()).isGreaterThan(256);
    }

    @Test
    void rejectsStreamingUnsupportedRolesAndOversizedInput() {
        assertThatThrownBy(() -> service.validate(new ChatRequest("modelhub-chat",
                List.of(new Message("user", "hello")), 10, 1.0, true), model))
                .isInstanceOfSatisfying(GatewayException.class, error -> assertThat(error.code()).isEqualTo("stream_not_supported"));
        assertThatThrownBy(() -> service.validate(new ChatRequest("modelhub-chat",
                List.of(new Message("tool", "result")), 10, 1.0, false), model))
                .isInstanceOf(GatewayException.class);
        properties.setMaxInputBytes(4);
        assertThatThrownBy(() -> service.validate(new ChatRequest("modelhub-chat",
                List.of(new Message("user", "hello")), 10, 1.0, false), model))
                .isInstanceOf(GatewayException.class);
    }

    @Test
    void requiresConsistentIntegralUsageFromTheProvider() {
        var json = JsonMapper.builder().build();
        assertThat(service.usage(json.readTree("{\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":3,\"total_tokens\":15}}")))
                .isEqualTo(new Usage(12, 3));
        assertThatThrownBy(() -> service.usage(json.readTree("{\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":3,\"total_tokens\":99}}")))
                .isInstanceOfSatisfying(GatewayException.class, error -> assertThat(error.code()).isEqualTo("upstream_usage_invalid"));
        assertThatThrownBy(() -> service.usage(json.readTree("{\"choices\":[]}")))
                .isInstanceOfSatisfying(GatewayException.class, error -> assertThat(error.code()).isEqualTo("upstream_usage_missing"));
    }

    @Test
    void successfulCompletionForwardsTheProviderAnswerAndSettlesRealUsage() {
        Identity identity = new Identity(10, "key:test", "test");
        Entry entry = new Entry("request-1", 10, 1, "modelhub-chat", "f".repeat(64),
                1000, "PENDING", null, null, 100, 400);
        when(upstream.configured()).thenReturn(true);
        when(ledger.reserve(eq(identity), eq("idem-1"), anyString(), any(Model.class), anyLong()))
                .thenReturn(new Reservation(entry, true));
        when(upstream.send(anyString())).thenReturn(new GatewayUpstreamClient.Response(200,
                "{\"id\":\"provider-1\",\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"你好\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":3,\"total_tokens\":15}}",
                "provider-1"));
        when(ledger.settle(eq("request-1"), eq(new Usage(12, 3)), anyString())).thenReturn(true);

        Completion completion = service.complete(identity, new ChatRequest("modelhub-chat",
                List.of(new Message("user", "你好")), 64, 0.7, false), "idem-1");

        assertThat(completion.requestId()).isEqualTo("request-1");
        assertThat(completion.response()).containsEntry("model", "modelhub-chat");
        assertThat(completion.response().get("usage")).isEqualTo(java.util.Map.of(
                "prompt_tokens", 12L, "completion_tokens", 3L, "total_tokens", 15L));
        verify(limiter).check("key:test");
        verify(ledger).providerRequestId("request-1", "provider-1");
        verify(ledger).settle(eq("request-1"), eq(new Usage(12, 3)), contains("你好"));
    }

    @Test
    void upstreamOnlyAllowsHttpsExceptForLocalDevelopment() {
        properties.setBaseUrl("https://provider.example/v1/");
        assertThat(new GatewayUpstreamClient(properties).endpoint().toString())
                .isEqualTo("https://provider.example/v1/chat/completions");
        properties.setBaseUrl("http://provider.example/v1");
        assertThatThrownBy(() -> new GatewayUpstreamClient(properties).endpoint())
                .isInstanceOfSatisfying(GatewayException.class, error -> assertThat(error.code()).isEqualTo("gateway_not_configured"));
        properties.setBaseUrl("http://127.0.0.1:9000/v1");
        assertThat(new GatewayUpstreamClient(properties).endpoint().toString())
                .isEqualTo("http://127.0.0.1:9000/v1/chat/completions");
    }
}
