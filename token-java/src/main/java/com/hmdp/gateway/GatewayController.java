package com.hmdp.gateway;

import com.hmdp.dto.Result;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

import static com.hmdp.gateway.GatewayTypes.*;

@RestController
public class GatewayController {
    private final GatewayService service;
    private final GatewayKeyService keys;
    private final GatewayLedger ledger;

    public GatewayController(GatewayService service, GatewayKeyService keys, GatewayLedger ledger) {
        this.service = service;
        this.keys = keys;
        this.ledger = ledger;
    }

    @GetMapping("/gateway/models")
    public Result models() { return Result.ok(service.models()); }

    @GetMapping("/gateway/api-keys")
    public Result listKeys() { return Result.ok(keys.list(keys.session().userId())); }

    public record CreateKey(String name) {}

    @PostMapping("/gateway/api-keys")
    public Result createKey(@RequestBody CreateKey request, HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return Result.ok(keys.create(keys.session().userId(), request.name()));
    }

    @DeleteMapping("/gateway/api-keys/{id}")
    public Result deleteKey(@PathVariable String id) { keys.revoke(keys.session().userId(), id); return Result.ok(); }

    @GetMapping("/gateway/usage")
    public Result usage(@RequestParam(defaultValue = "1") int current) { return ledger.usage(keys.session().userId(), current); }

    @GetMapping("/v1/models")
    public Map<String, Object> apiModels(@RequestHeader(value = "Authorization", required = false) String authorization) {
        keys.authenticate(authorization);
        return service.apiModels();
    }

    @PostMapping("/v1/chat/completions")
    public Map<String, Object> chat(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @RequestHeader(value = "Idempotency-Key", required = false) String idempotency,
                                   @RequestBody ChatRequest request, HttpServletResponse response) {
        return complete(keys.authenticate(authorization), request, idempotency, response);
    }

    @PostMapping("/gateway/chat/completions")
    public Map<String, Object> playground(@RequestHeader(value = "Idempotency-Key", required = false) String idempotency,
                                         @RequestBody ChatRequest request, HttpServletResponse response) {
        return complete(keys.session(), request, idempotency, response);
    }

    private Map<String, Object> complete(Identity identity, ChatRequest request, String idempotency, HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        Completion completion = service.complete(identity, request, idempotency);
        response.setHeader("X-Request-Id", completion.requestId());
        return completion.response();
    }
}
