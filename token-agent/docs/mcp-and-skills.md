# ModelHub MCP 与项目 Skills

## 能力边界

`modelhub_mcp` 是基于官方 Python MCP SDK 2.0 的标准服务，支持 stdio 和 Streamable HTTP。当前只暴露公共只读能力：

- `modelhub_hot_models`
- `modelhub_search_models`
- `modelhub_get_model`
- `modelhub_list_packages`
- `modelhub_get_package`
- `modelhub_hot_packages`
- `modelhub_estimate_cost`

前 6 个工具查询 Java 公共数据；标准 MCP 的成本工具是纯本地 Decimal 计算，调用方必须传入输入/输出 Token、请求次数和两种“分/百万 Token”单价。它不接收 `model_id`、也不会自行查询价格，因此调用方应先通过公共模型查询取得权威单价。

用户订单、额度账户、购买、支付、退款、额度调整和 API Key 操作不通过 MCP 暴露。订单与账户工具需要先完成 MCP OAuth/主体绑定，不能把认证 Token 作为模型可填写的工具参数。

## 运行 MCP

安装依赖：

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
```

本地 stdio（适合 Codex 直接启动）：

```powershell
.\.venv-win\Scripts\python.exe -m modelhub_mcp.server
```

Streamable HTTP：

```powershell
.\.venv-win\Scripts\python.exe -m modelhub_mcp.server --transport streamable-http --host 127.0.0.1 --port 8010
```

HTTP 地址是 `http://127.0.0.1:8010/mcp`。生产环境若监听非回环地址，必须在反向代理层增加 TLS、来源限制和认证。

也可以通过 Compose 启动独立服务：

```powershell
docker compose up -d modelhub-mcp
```

Compose 同样只把 `8010` 绑定到宿主机的 `127.0.0.1`，不会直接暴露到公网。

Codex 项目级 HTTP 配置示例（`.codex/config.toml`）：

```toml
[mcp_servers.modelhub]
url = "http://127.0.0.1:8010/mcp"
default_tools_approval_mode = "writes"
tool_timeout_sec = 30
```

也可以配置 stdio，将 `command` 指向项目虚拟环境 Python，并设置 `args = ["-m", "modelhub_mcp.server"]` 与项目 `cwd`。

## 项目 Skills

仓库级 Skill 位于 `.agents/skills/`，Codex 可自动发现；项目运行时的 `ProjectSkillRegistry` 读取同一目录，并根据意图和协作 Agent 把可信工作流注入 system prompt：

- `modelhub-model-selection`
- `modelhub-cost-estimation`
- `modelhub-quota-order`
- `modelhub-api-troubleshooting`
- `modelhub-risk-review`

`/chat` 响应的 `skills_used` 字段用于确认本轮实际采用的 Skill。客户端不能直接提交 Skill 正文或覆盖 system prompt。

## 主应用的 Agent tool-use 循环

主 FastAPI 应用现在不仅注入 Skill，还会让 Agent 在代码限定的只读白名单内参与工具选择。它复用进程内的 `MCPToolManager`，不会通过 HTTP 回调自己的 `modelhub_mcp` 服务：

```text
/chat
→ 读取记忆
→ 意图识别和实体提取
→ 选择 Agent + 注入对应 Skill
→ 代码生成 ToolPolicy（能力 ∩ 可用工具 ∩ 本次请求约束）
→ Anthropic tool_use
→ MCPToolManager 执行、校验、超时、缓存、熔断
→ tool_result 回传模型
→ 最终回答和安全工具元数据
```

内部 Manager 共注册 9 个 ModelHub 业务工具：6 个公共 Java 查询、1 个内部成本计算、2 个代码专用私有查询，另有 `knowledge_search`。模型白名单最多包含前 7 个公共/计算工具和知识工具；`token_order`、`token_account` 永不向模型暴露。

模型可见的工具按 Agent 分配：

| Agent | 可见只读工具 |
|---|---|
| 模型选型 | 热门模型、搜索、模型详情、模型套餐、知识库 |
| 成本优化 | 热门/搜索/模型详情、按 `model_id` 实时取价的确定性成本计算、知识库 |
| 套餐订单 | 模型套餐、套餐详情、热门套餐、知识库 |
| API 支持 | 模型搜索/详情、知识库 |
| 风控与人工复核 | 知识库 |

有明确 `model_id`、`package_id` 或模型关键词时，代码会强制首个权威查询；其他允许场景使用 `auto` 或 `any`，由模型决定是否及如何组合工具。强制选择只用于首轮，后续恢复 `auto`，防止无限调用。

每个请求默认最多 3 个工具轮次、4 次实际执行、同轮最多 3 个并发调用。相同工具与参数不会重复执行；越权工具、未知参数和超预算调用均作为安全错误回传；达到上限后执行一次不带 `tools` 的最终总结。单个结果最多 8000 字符，工具结果被明确视为不可信数据而非指令。

首轮指定具体工具或 `any` 时属于 required evidence：工具不可用、模型未调用、调用失败/fallback，或同轮没有权威成功结果都会失败关闭，系统只返回“无法核验”，不会用自由生成答案冒充实时证据。首轮 `auto` 属于 optional：错误可回传模型并明确降级；只有 400/404/422 明确表示网关不支持 tools 才能直接切换无工具回答，401、429、超时和普通服务错误不会触发这个兼容分支。工具成功后若后续 LLM 失败，既有审计记录仍会保留。

主应用内部同名 `modelhub_estimate_cost` 与标准 MCP 的参数契约不同：内部工具接收 `model_id`、Token 数和请求次数，先调用 Java 模型详情取得 `inputPrice/outputPrice` 原始分价，再做 Decimal 计算并标记价格来源；标准 MCP 则由调用方传价、不访问 Java。

订单和额度账户属于私有只读数据，仍由应用代码根据请求对象与认证状态确定性预取，绝不出现在模型工具白名单中。订单查询要求同时提供 `order_id` 和明确订单动作；账户查询要求“我的余额/额度/用量”等明确短语，普通成本或用量问题不会触发私有访问。认证只接受 `Authorization: Bearer <token>`；旧的请求体 Token 默认关闭。私有工具不缓存、不使用共享默认 Token，并按 `token_order` / `token_account` 各自的业务字段 allowlist 投影结果，未知字段、凭据和 PII 不进入模型上下文。

`/chat` 新增安全审计字段：

- `tools_used`：实际执行过的工具名，稳定去重；
- `authoritative_tools_used`：成功、非 fallback 且可作为权威证据的工具名；
- `tool_call_count`：实际执行次数；
- `tool_rounds`：模型产生 tool-use 的轮数；
- `tool_limit_reached`：是否因轮次或次数预算强制结束；
- `knowledge_used` / `business_data_used`：仅成功、非 fallback、权威结果才为 `true`。

相关环境变量：

```dotenv
AGENT_TOOL_USE_ENABLED=true
AGENT_TOOL_MAX_ROUNDS=3
AGENT_TOOL_MAX_CALLS=4
AGENT_TOOL_MAX_PARALLEL_CALLS=3
AGENT_TOOL_RESULT_MAX_CHARS=8000
ALLOW_LEGACY_BODY_AUTH_TOKEN=false
MODELHUB_DEBUG_PRIVATE_TOOLS=false
```

## 验证

```powershell
.\.venv-win\Scripts\python.exe -B -m unittest discover -s tests -v
```

各 Skill 还应通过仓库所用 `skill-creator` 的 `quick_validate.py` 校验。
