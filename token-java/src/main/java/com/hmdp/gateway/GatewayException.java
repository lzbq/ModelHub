package com.hmdp.gateway;

/** Only these deliberately sanitized messages may be returned to a caller. */
public class GatewayException extends RuntimeException {
    private final int status;
    private final String code;
    private String requestId;

    public GatewayException(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public int status() { return status; }
    public String code() { return code; }
    public String requestId() { return requestId; }
    public GatewayException withRequestId(String value) { this.requestId = value; return this; }
}
