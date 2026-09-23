package com.hmdp.gateway;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = GatewayController.class)
public class GatewayExceptionAdvice {
    @ExceptionHandler(GatewayException.class)
    public ResponseEntity<Object> known(GatewayException error, HttpServletRequest request) {
        return response(error.status(), error.code(), error.getMessage(), error.requestId(), request);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Object> malformed(HttpServletRequest request) {
        return response(400, "invalid_request_error", "请求 JSON 格式或字段类型不正确", null, request);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Object> unknown(HttpServletRequest request) {
        // Do not include database errors, Authorization headers, upstream bodies, or prompts.
        return response(503, "gateway_unavailable", "网关暂不可用，请检查服务配置或稍后重试", null, request);
    }

    private ResponseEntity<Object> response(int status, String code, String message, String requestId, HttpServletRequest request) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("error", Map.of("message", message, "type", status >= 500 ? "api_error" : "invalid_request_error", "code", code));
        if (request.getRequestURI().startsWith("/gateway/") && !request.getRequestURI().endsWith("/chat/completions")) {
            payload.put("success", false);
            payload.put("errorMsg", message);
        }
        ResponseEntity.BodyBuilder builder = ResponseEntity.status(status).header("Cache-Control", "no-store");
        if (requestId != null) builder.header("X-Request-Id", requestId);
        if (status == 429) builder.header("Retry-After", "60");
        return builder.body(payload);
    }
}
