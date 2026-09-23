---
name: modelhub-api-troubleshooting
description: Diagnose ModelHub API and SDK failures, authentication, request parameters, model names, rate limits, timeouts, and HTTP error codes. Use for 401, 403, 404, 429, 5xx, networking, or integration problems; do not use for billing disputes.
---

# ModelHub API 排障

1. 先确认症状、HTTP 状态码、SDK/语言、端点、模型名和最近变更；只索取脱敏后的请求片段、响应体和 request ID。
2. 按优先级排查：端点与网络 → 鉴权头格式 → 模型/参数 → 配额与限流 → 服务端异常。一次给出可执行、可验证的检查步骤。
3. 模型名不确定时调用 `modelhub_search_models` 或 `modelhub_get_model` 核对，不猜测可用模型。
4. 401/403 检查凭据是否存在、权限和头格式；404 检查 URL 与模型；429 检查速率/并发并使用退避；5xx/超时记录 request ID、时间和最小复现后再重试或升级。
5. 示例代码必须从环境变量读取密钥，设置超时，并避免日志输出认证头。绝不要求用户粘贴完整 API Key、认证 Token 或私密连接串。
6. 明确区分已验证原因与待验证假设；若平台侧状态不可见，说明需要运维或人工复核。
