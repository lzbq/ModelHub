---
name: modelhub-model-selection
description: Select and compare ModelHub models for a concrete workload. Use for model discovery, recommendation, provider comparison, context-window, latency, quality, or price trade-offs; do not use for API debugging or account disputes.
---

# ModelHub 模型选型

1. 先确认任务类型、输入输出模态、质量要求、上下文长度、延迟目标、调用量和预算。信息不足时，只追问最影响结论的一项。
2. 有明确模型或关键词时调用 `modelhub_search_models`；没有明确候选时调用 `modelhub_hot_models`。对入围模型调用 `modelhub_get_model`，需要套餐信息时再调用 `modelhub_list_packages`。
3. 若 MCP 工具不可用，只能依据当前对话中明确提供的 ModelHub 实时数据；不得补造模型、价格、上下文或库存。
4. 至少比较能力匹配、价格、延迟/吞吐、上下文和限制。Java 字段 `inputPrice`、`outputPrice` 的单位是人民币分/百万 Token，展示人民币元时除以 100。
5. 输出一个首选和最多一个备选，分别说明适用理由、关键取舍、依据和仍需验证的假设。
6. 不执行购买、支付、额度调整或 API Key 操作；涉及交易时引导用户回到业务页面确认。
