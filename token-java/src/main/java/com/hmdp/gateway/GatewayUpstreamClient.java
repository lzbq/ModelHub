package com.hmdp.gateway;

import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.net.ConnectException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Flow;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
/*
* 服务端代理真实上游
网关持有供应商 API Key，客户端拿不到真实供应商 Key。
上游地址默认配置为阿里云百炼 OpenAI 兼容接口。
只允许 HTTPS 上游，localhost 开发环境可用 HTTP。
控制超时和响应体大小，并记录上游 x-request-id。
* */
@Component
public class GatewayUpstreamClient {
    public record Response(int status, String body, String providerRequestId) {}
    public static class Failure extends RuntimeException {
        private final boolean definitelyNotSent;
        public Failure(boolean definitelyNotSent) {
            super("Upstream transport failed");
            this.definitelyNotSent = definitelyNotSent;
        }
        public boolean definitelyNotSent() { return definitelyNotSent; }
    }

    private final GatewayProperties properties;
    private final HttpClient http;

    public GatewayUpstreamClient(GatewayProperties properties) {
        this.properties = properties;
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    public URI endpoint() {
        try {
            String base = properties.getBaseUrl().strip().replaceAll("/+$", "");
            URI uri = URI.create(base);
            boolean local = List.of("localhost", "127.0.0.1", "[::1]").contains(uri.getHost());
            if ((!"https".equals(uri.getScheme()) && !(local && "http".equals(uri.getScheme())))
                    || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException();
            }
            return URI.create(base + "/chat/completions");
        } catch (RuntimeException e) {
            throw new GatewayException(503, "gateway_not_configured", "模型网关尚未配置有效的上游地址");
        }
    }

    public boolean configured() {
        if (!properties.isEnabled() || properties.getApiKey().isBlank() || properties.getBaseUrl().isBlank()) return false;
        try { endpoint(); return true; } catch (GatewayException e) { return false; }
    }

    public Response send(String payload) {
        int timeout = Math.max(1, Math.min(300, properties.getTimeoutSeconds()));
        HttpRequest request = HttpRequest.newBuilder(endpoint()).timeout(Duration.ofSeconds(timeout))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + properties.getApiKey())
                .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8)).build();
        int limit = Math.max(1024, Math.min(4194304, properties.getMaxResponseBytes()));
        CompletableFuture<HttpResponse<byte[]>> future = http.sendAsync(request, info -> new LimitedBodySubscriber(limit));
        try {
            // Covers the whole response body, including an upstream that sends headers then stalls.
            HttpResponse<byte[]> response = future.get(timeout, TimeUnit.SECONDS);
            String providerId = response.headers().firstValue("x-request-id").orElse(null);
            return new Response(response.statusCode(), new String(response.body(), StandardCharsets.UTF_8), providerId);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            future.cancel(true);
            throw new Failure(false);
        } catch (TimeoutException e) {
            future.cancel(true);
            throw new Failure(false);
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            while (cause != null && !(cause instanceof ConnectException) && !(cause instanceof HttpConnectTimeoutException) && cause.getCause() != null) {
                cause = cause.getCause();
            }
            throw new Failure(cause instanceof ConnectException || cause instanceof HttpConnectTimeoutException);
        }
    }

    private static final class LimitedBodySubscriber implements HttpResponse.BodySubscriber<byte[]> {
        private final int limit;
        private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        private final CompletableFuture<byte[]> body = new CompletableFuture<>();
        private Flow.Subscription subscription;
        LimitedBodySubscriber(int limit) { this.limit = limit; }
        public CompletionStage<byte[]> getBody() { return body; }
        public void onSubscribe(Flow.Subscription value) { subscription = value; value.request(1); }
        public void onNext(List<ByteBuffer> chunks) {
            for (ByteBuffer chunk : chunks) {
                if ((long) buffer.size() + chunk.remaining() > limit) {
                    subscription.cancel();
                    body.completeExceptionally(new IllegalStateException("Response exceeded configured size limit"));
                    return;
                }
                byte[] bytes = new byte[chunk.remaining()];
                chunk.get(bytes);
                buffer.writeBytes(bytes);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { body.completeExceptionally(error); }
        public void onComplete() { body.complete(buffer.toByteArray()); }
    }
}
