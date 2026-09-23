package com.hmdp.gateway;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.ByteArrayInputStream;
import java.io.IOException;

/** Bound the wire JSON before deserialization, including chunked requests and ignored JSON fields. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class GatewayBodyLimitFilter extends OncePerRequestFilter {
    private static final int MAX_BODY = 512 * 1024;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getServletPath().isEmpty() ? request.getRequestURI() : request.getServletPath();
        return !"POST".equals(request.getMethod()) || !java.util.Set.of(
                "/v1/chat/completions", "/gateway/chat/completions", "/gateway/api-keys").contains(path);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        byte[] body = request.getContentLengthLong() > MAX_BODY ? null : request.getInputStream().readNBytes(MAX_BODY + 1);
        if (body == null || body.length > MAX_BODY) {
            response.setStatus(413);
            response.setContentType("application/json");
            response.setCharacterEncoding("UTF-8");
            response.getWriter().write("{\"error\":{\"message\":\"请求正文超过 512 KiB 限制\",\"type\":\"invalid_request_error\",\"code\":\"request_too_large\"}}");
            return;
        }
        chain.doFilter(new HttpServletRequestWrapper(request) {
            @Override public ServletInputStream getInputStream() {
                ByteArrayInputStream bytes = new ByteArrayInputStream(body);
                return new ServletInputStream() {
                    public int read() { return bytes.read(); }
                    public int read(byte[] target, int offset, int length) { return bytes.read(target, offset, length); }
                    public boolean isFinished() { return bytes.available() == 0; }
                    public boolean isReady() { return true; }
                    public void setReadListener(ReadListener listener) { throw new UnsupportedOperationException("Synchronous body only"); }
                };
            }
        }, response);
    }
}
