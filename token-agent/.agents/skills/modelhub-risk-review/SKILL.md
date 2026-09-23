---
name: modelhub-risk-review
description: Assess ModelHub abnormal usage, suspected API-key theft or sharing, bulk purchasing, account restrictions, complaints, and ownership disputes. Use when evidence must be separated from conclusions and a human-review decision is needed; do not use for ordinary API errors.
---

# ModelHub 风险复核

1. 将内容分为已知事实、风险信号、合理替代解释和缺失证据；不能仅凭单次异常直接认定违规或归责。
2. 建议收集脱敏的 request ID、时间范围、IP/设备变化、调用量基线、模型与状态码。不得索取或回显完整 API Key、认证 Token、密码或支付凭据。
3. 优先建议可逆的安全措施：暂停可疑密钥、轮换密钥、缩小权限、设置限额与告警、保留审计记录。不要声称已替用户执行这些操作。
4. 涉及封禁、额度扣除、退款、订单归属、账号申诉或证据冲突时，必须标记平台侧人工复核，并说明需要复核的具体证据。
5. 输出结论使用“已确认 / 高可能 / 待验证”分级，并给出下一步和安全边界。
