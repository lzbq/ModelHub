---
name: modelhub-quota-order
description: Explain ModelHub Token packages, inventory, quota, orders, payment status, credit arrival, and validity. Use for package comparison or order/account questions; do not use for general model selection unless package data is required.
---

# ModelHub 套餐与订单

1. 套餐发现使用 `modelhub_hot_packages`；已知套餐调用 `modelhub_get_package`；已知模型需要可购套餐时调用 `modelhub_list_packages`。
2. 区分平台规则、实时查询状态、可能原因和下一步操作。Java `payValue` 单位是人民币分，展示人民币元时除以 100；`tokenQuota` 才是 Token 数量。
3. 估算可用时间时使用 `tokenQuota ÷（日调用次数 × 每次输入输出 Token 总和）`，并复核数量级。
4. 当前 MCP 首版不公开用户订单和额度账户工具。不得索要或让用户把认证 Token/API Key 作为工具参数提供；只能使用主应用已安全注入到背景中的已认证查询结果。
5. 不声称已经抢购、支付、退款、充值或调整额度，不承诺库存或必然抢到；强事务操作必须回到业务页面由用户确认。
6. 若订单归属、扣款、退款或额度到账无法从已认证数据确认，明确标记平台侧人工复核。
