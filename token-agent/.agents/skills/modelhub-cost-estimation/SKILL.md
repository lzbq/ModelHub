---
name: modelhub-cost-estimation
description: Estimate and optimize ModelHub Token usage and cost. Use when a user provides or asks about request volume, input/output tokens, model prices, daily or monthly spend, budget, caching, routing, or savings; do not use for order-status disputes.
---

# ModelHub 成本估算

1. 收集调用次数、平均输入 Token、平均输出 Token、周期和模型价格。缺失关键值时明确列出假设，优先给区间而不是伪精确结果。
2. 价格未知时先用 `modelhub_search_models` 或 `modelhub_get_model` 获取实时价格；不要引用对话和工具结果之外的价格或折扣。
3. 调用 `modelhub_estimate_cost` 进行确定性计算。输入/输出价格口径是人民币分/百万 Token，人民币元成本公式为：`Token × 次数 × 分价 ÷ 1,000,000 ÷ 100`。
4. 分别展示输入 Token、输出 Token、输入成本、输出成本、合计、周期和关键假设，并复核数量级和分转元。
5. 优化建议按影响排序，可包含小模型分流、缓存、Prompt 精简和批处理；节省金额必须基于清晰的前后假设重新计算。
6. 工具或价格不可用时说明阻塞点，不编造精确成本。
