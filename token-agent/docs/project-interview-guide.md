# ModelHub Token Agent 项目面经

> 面向大模型应用、Agent、RAG、MCP、后端架构和 Python 工程岗位。内容依据当前仓库实现整理，核对日期：2026-09-22。

## 1. 这份面经怎么用

这不是一份只背概念的题库，而是一套“项目介绍 → 原理解释 → 代码落点 → 设计取舍 → 风险与改进”的面试表达模板。

建议分三轮准备：

1. 先熟练背诵 30 秒和 2 分钟项目介绍。
2. 重点掌握 Agent、tool-use、RAG、Memory 四条核心链路。
3. 再准备评测、监控、安全、部署和故障排查等高级追问。

回答项目问题时尽量使用“业务问题 → 方案 → 请求流程 → 风险控制 → 局限 → 优化”的结构。

## 2. 项目介绍模板

### 2.1 30 秒版本

这是一个面向大模型 API 商城的智能助手。Vue 前端把模型目录、套餐交易、真实模型体验和 Agent 对话放在同一产品中；Agent 侧支持模型选型、Token 成本估算、套餐订单咨询、API 排障和风险复核。主链路使用意图识别加多 Agent 编排，并实现受策略约束的 LLM tool-use 循环；知识问答使用 Milvus RAG；会话侧采用 Redis 工作记忆、摘要记忆、Milvus 情景记忆和用户画像。项目还提供标准 MCP 服务和仓库级 Skills，并配套端到端评测与监控。

### 2.2 2 分钟版本

这个项目解决的是大模型服务商城里“知识问答、实时业务数据、个性化上下文和高风险操作边界”混在一起的问题。

用户从 Vue 对话页发起请求，开发环境下 `/agent/chat` 经 Vite 代理改写为 FastAPI 的 `/chat`。系统读取多层记忆，再由 IntentRecognizer 识别意图、紧急度和实体。AgentOrchestrator 根据结果选择**模型顾问、成本优化、套餐订单、API 支持或风险复核 Agent**；普通问候、反馈和未覆盖意图使用 GeneralAgent，复杂问题可以并行调用多个 Agent。

每个 Agent 会加载对应的项目 Skill 作为可信 system 指令。对于模型、价格、套餐和知识库查询，LLM 可以通过 AgentToolLoop 决定是否调用工具，但代码仍控制白名单、参数 Schema、锁定输入、调用轮次、并发数和结果长度。强制实时核验的请求如果拿不到权威工具结果会失败关闭，不能让模型直接编答案。订单和账户属于私有数据，不暴露给模型选择，而是由 API 根据明确意图和 Bearer 身份确定性预取。

RAG 侧会进行查询改写、多路向量召回、内容去重和 LLM 重排。Memory 侧把短期工作记忆放 Redis，长对话压缩为摘要，同时把情景记忆和用户画像放 Milvus。压缩使用 WATCH/MULTI/EXEC 做 CAS，避免 LLM 摘要期间并发新消息被覆盖。

Java 侧另有统一模型调用网关：它隐藏供应商密钥和模型 ID 差异，通过平台 API Key 或登录会话鉴权，在调用百炼等 OpenAI 兼容上游前预留套餐额度，并按真实 usage 结算。对外还提供独立的标准 MCP 服务，只暴露 7 个公共只读工具，供 Codex 等 MCP Client 使用。最后通过硬规则、LLM Judge、回归基线、运行监控和安全审计字段保证系统可评测、可观察。

### 2.3 项目背景，以及为什么做这个项目

大模型应用团队通常会同时遇到四类问题：模型和供应商很多，选型与价格难比较；调用前不知道成本；购买套餐后的订单、库存和额度属于实时业务数据；API Key、错误码和异常用量又需要技术支持。单独使用供应商控制台只能解决“调用模型”，普通商城只能解决“购买”，通用聊天机器人又无法安全读取真实订单和额度。

因此项目把三条链闭环连接起来：Java 负责交易、额度和统一模型网关，Python 负责多 Agent、RAG、Memory 和受控工具调用，Vue 负责用户操作入口。用户可以完成“选模型 → 算成本 → 买套餐 → 获得额度 → 创建平台 Key → 调真实模型 → 查 usage → 找 Agent 排障”的完整流程。

面试短答：

> 我做这个项目不是为了再封装一个聊天接口，而是想解决大模型服务从选型、购买到调用和售后的断层。真实价格、库存、订单和余额由 Java 业务系统管理，Agent 只在受控权限下查询和解释；统一网关负责隐藏供应商差异、保护上游密钥并把真实 usage 与用户额度结算起来。这样既能展示高并发交易和网关计费，也能展示 Agent 如何安全使用业务事实。

### 2.4 一句话技术亮点

让模型拥有“选择工具的判断权”，但不拥有“扩大权限、修改参数边界和绕过实时证据”的执行权。

## 3. 总体架构与请求链路

```mermaid
flowchart LR
    U["用户"] --> WEB["Vue 3 前端"]
    WEB -->|"/agent/chat → /chat"| API["FastAPI /chat"]
    WEB -->|"/api/*"| JAVA["ModelHub Java API"]
    WEB -->|"/api/gateway/chat/completions"| GATEWAY["Java 模型网关"]
    EXT["外部应用"] -->|"/v1/chat/completions + mh_ Key"| GATEWAY
    API --> MEM["MemoryManager"]
    API --> PRIVATE["私有数据确定性预取"]
    API --> ORC["AgentOrchestrator"]
    ORC --> INTENT["IntentRecognizer"]
    ORC --> SKILL["ProjectSkillRegistry"]
    ORC --> AGENT["专属 Agent / 并行 Agent"]
    AGENT --> LOOP["AgentToolLoop"]
    LOOP --> TM["MCPToolManager"]
    TM --> KB["KnowledgeBase / Milvus"]
    TM --> JAVA
    AGENT --> LLM["Anthropic 兼容 LLM"]
    GATEWAY --> UPSTREAM["百炼等 OpenAI 兼容上游"]
    MEM --> REDIS["Redis"]
    MEM --> VM["Milvus 情景记忆 / 画像"]
    MEM --> PG["PostgreSQL 可选审计"]

    CLIENT["Codex / MCP Client"] --> MCP["独立 modelhub_mcp"]
    MCP --> JAVA
```

主应用中最重要的六条链路是：

1. 前端：Vue `/agent/chat` → Vite 改写为 FastAPI `/chat`；登录页面通过 `/api/gateway/chat/completions` 调 Java 网关，外部应用通过 `/v1/chat/completions` 和 `mh_` Key 调用。
2. `/chat`：记忆读取 → 私有数据预取 → 意图识别 → Agent 路由 → tool-use/RAG → 记忆写入。
3. Agent：意图与紧急度 → 专属 Agent → Skill system 指令 → 有界工具循环。
4. RAG：查询改写 → 多路召回 → 去重 → 重排 → Top-K。
5. Memory：Redis 工作记忆/摘要 + Milvus 情景记忆/画像 + 可选 PostgreSQL 审计。
6. 外部 MCP：MCP Client → 标准 MCP Server → 公共 Java 查询或本地成本计算。

核心代码入口：

| 模块 | 文件 | 关键入口 |
|---|---|---|
| HTTP 装配 | api/main.py | lifespan、chat、_chat_impl |
| Agent 编排 | agents/agent_orchestrator.py | AgentOrchestrator.run、run_parallel |
| 模型工具循环 | agents/tool_use.py | AgentToolLoop.run |
| 意图识别 | core/intent_recognizer.py | IntentRecognizer.recognize |
| 项目 Skills | core/project_skills.py | ProjectSkillRegistry.resolve |
| 内部工具框架 | modelhub_tools/tool_manager.py | MCPToolManager.call、search_with_rewrite |
| 知识库 | modelhub_tools/knowledge_base.py | KnowledgeBase.search_handler |
| 记忆 | memory/conversation_memory.py | get_context、add_message、_compress |
| 向量存储 | storage/vector_store.py | TextEmbedder、MilvusTextStore |
| 评测 | evaluation/evaluator.py | EndToEndEvaluator.run |
| 监控 | monitor/performance_monitor.py | PerformanceMonitor |
| 标准 MCP | modelhub_mcp/server.py | main、7 个工具定义 |
| Vue 对话入口 | token-web/src/views/ChatView.vue | `/agent/chat`、`user_id` 字符串化 |
| Vite 路由代理 | token-web/vite.config.ts | `/api`、`/agent`、`/v1` 转发 |
| Java 模型网关 | token-java/.../gateway/GatewayService.java | 校验、预留、上游调用、usage 结算 |

## 4. Agent 模块面经

### 4.1 Agent 模块解决什么问题

单一 Prompt 很难同时处理模型选型、实时价格、订单解释、API 排障和风险争议，因为这些任务需要不同的知识、工具权限、审核强度和回答风格。

项目没有让一个“大而全”的 Agent 自由行动，而是拆成多个职责明确的角色：

- GENERAL：通用兜底；
- MODEL_ADVISOR：模型发现、比较和推荐；
- COST_OPTIMIZER：Token 用量、成本和优化；
- QUOTA_ORDER：套餐、库存、订单和额度；
- API_SUPPORT：SDK、鉴权、限流和接口排障；
- QUOTA_RISK：异常使用、密钥盗用、账号争议；
- MANUAL_REVIEW：高风险路由和审核语义。

这样拆分的主要收益：

1. system prompt 和 Skill 更聚焦；
2. 每类 Agent 可以使用不同工具白名单；
3. 风险类请求可以强制人工复核；
4. 可分别统计成功率、延迟和路由表现；
5. 复杂问题可以并行协作。

代价是路由错误、重复调用、结果冲突和更高的 LLM 成本，因此项目又增加了意图识别、工具预算、稳定合并顺序和运行时路由惩罚。

### 4.2 AgentOrchestrator 执行流程

```text
Request
→ IntentRecognizer 识别 intent / urgency / entities
→ 根据意图和紧急度选择主 Agent
→ 根据消息中的复合领域决定是否并行协作
→ 为每个 Agent 解析对应 Skill
→ 生成当前请求的 ToolPolicy
→ Agent 调用 LLM，并按需进入 AgentToolLoop
→ 合并 AgentResponse、工具审计和审核标记
→ 返回 OrchestratorResult
```

串行路径适合单一问题；并行路径用于同时包含模型、成本、套餐或风险的复合问题。并行时主意图对应的 Agent 排在最前面，工具总预算通过 divmod 精确切分，避免每个协作者都拿到完整预算。

### 4.3 高频问题：为什么不用一个 Agent

参考回答：

> 单 Agent 的优点是简单、上下文统一，但这个项目不同领域的工具权限和风险差异很大。例如模型顾问可以查询公共模型，订单 Agent 涉及私有数据，风险 Agent 必须区分证据与结论。如果全部放进一个 Prompt，工具 schema 太多、误调用概率更高，也很难单独评估某类能力。因此我用编排器做职责拆分，同时保留 GeneralAgent 作为可控兜底。为了降低多 Agent 成本，只在检测到复合领域时并行，并对工具预算进行切分。

追问：多 Agent 一定比单 Agent 好吗？

> 不一定。简单问答使用多 Agent 会增加延迟和成本；路由不准时还可能让多个 Agent 给出冲突答案。生产中应通过离线评测和线上数据证明拆分收益，并考虑用一个强模型加少量专家工具替代过度拆分。

#### 这几类 Agent 为什么这样设计

拆分依据不是页面或技术名词，而是**业务目标、事实来源、工具权限和失败风险**。同一类问题共享一组 Prompt、Skill、工具白名单和评测标准，风险差异大的问题则必须分开。

| Agent | 负责的问题 | 主要事实/工具 | 单独拆分的原因 |
|---|---|---|---|
| `ModelAdvisorAgent` | 模型发现、比较和选型 | 模型列表、详情、价格、知识库 | 要约束模型参数和价格必须来自实时目录，评测重点是推荐依据和事实正确性 |
| `CostOptimizerAgent` | Token 与日/月成本估算、用量优化 | 实时模型单价、确定性成本计算 | 金额计算需要固定公式、单位换算和假设展示，不能交给自由文本心算 |
| `QuotaOrderAgent` | 套餐、库存、订单、支付、额度到账 | 公共套餐工具，以及 API 层按登录身份预取的私有订单/账户 | 涉及用户私有数据和交易状态；只允许解释与引导，不能让模型直接执行支付或改额度 |
| `ApiSupportAgent` | API Key、SDK、参数、401/429/5xx 排查 | 模型详情、知识库 | 排障需要按顺序给检查步骤，并禁止用户泄露完整密钥 |
| `QuotaRiskAgent` / `MANUAL_REVIEW` 路由 | 刷购、Key 共享、盗用、异常调用和申诉 | 平台规则、有限证据、人工审核标记 | 风险结论影响封禁、退款和归属，必须限制为风险线索并保留人工复核；当前人工审核仍是逻辑路由，尚无独立工单 Agent |
| `GeneralAgent` | 问候、反馈、普通问答、未覆盖意图和受限降级 | 默认无工具；仅部分普通查询允许知识库 | 保证长尾问题可回答，同时把它的权限压到最小，避免通用 Agent 获得所有领域工具 |

面试回答：

> 我没有按模型数量拆 Agent，而是按业务责任和权限边界拆。模型选型看实时模型目录，成本 Agent 要保证计算口径，套餐订单涉及私有交易数据，API 支持强调密钥安全和排障流程，风控结论还需要人工复核。拆分后每类 Agent 可以绑定更短的 Prompt、专属 Skill、最小工具白名单和独立评测集。GeneralAgent 只承接长尾和安全降级，不拥有全部工具。这样比一个大 Prompt 更容易控制权限、成本和回归质量。

### 4.4 高频问题：如何选择主 Agent

> 先由 IntentRecognizer 输出意图和紧急度，再由确定性路由映射选择主 Agent。紧急度为 CRITICAL 或命中人工审核意图时优先进入审核语义。并行场景中仍以主意图映射结果作为主 Agent，关键词扫描只补充协作者，不能反过来改变主身份。

### 4.5 高频问题：并行 Agent 怎么避免状态串线

> Agent 实例会被并发复用，因此不能把 messages、工具轮次、重复签名或当前 Skill 放在实例属性里。项目使用 **dataclasses.replace** 为每个协作者创建 Request 副本；AgentToolLoop 的 conversation、seen_signatures、records 和预算全部是方法局部变量。并行执行使用 asyncio.gather(return_exceptions=True)，单个 Agent 异常不会直接取消其他结果。

### 4.6 高频问题：Agent 失败如何降级

Agent 降级分为“路由兜底、实例兜底、执行失败”和“权威证据失败”四种情况：

1. `FEEDBACK`、问候、普通 `QUERY/REQUEST`、低置信度变成的 `OTHER`，或者意图没有专属映射时，路由直接选择 `GeneralAgent`。
2. 已映射的目标类型当前没有可用实例时，`_route()` 或 `_execute()` 会尝试使用 `GeneralAgent`。
3. 专属 Agent 执行失败且本次工具只是可选能力时，系统给 GeneralAgent 注入“工具不可用、不得声称已核验实时事实”的降级上下文，并清空 ToolPolicy，让它只给通用解释和下一步建议。
4. 如果问题强制依赖当前价格、库存、订单、余额或平台规则，工具未启用、预算不足或权威调用失败时不会让 GeneralAgent 猜答案，而是失败关闭，返回“当前无法核验”。风险与人工审核场景继续设置 `review_required`。

需要特别说明：`fallback` 工具结果也不是权威证据；它可以用于解释服务暂不可用，但不能被包装成实时业务事实。若 GeneralAgent 自身也不存在或调用失败，接口最终返回服务暂不可用。

面试回答：

> GeneralAgent 有两个角色：一是承接没有专属领域映射的长尾问题，二是承接不依赖实时证据的专属 Agent 失败。是否允许降级取决于事实要求，而不是简单看有没有异常。普通概念解释可以带着明确的降级标记继续回答；当前价格、库存、订单、余额和风控结论必须拿到权威工具结果，失败时直接告诉用户无法核验。这样可用性不会以幻觉为代价。

### 4.7 Agent 模块的局限与优化

- 意图识别和 Agent 生成会产生多次模型调用，可通过小模型路由、规则短路或合并调用降本。
- 多 Agent 合并目前以分段拼接为主，可增加一个受限 synthesis 阶段解决冲突。
- 路由惩罚来自进程内统计，多 worker 不共享；可迁移到 Redis 或指标平台。
- MANUAL_REVIEW 目前更接近逻辑类型，生产应接入真正的审核任务系统。
- 外部工具还需处理缓存击穿、后端限流和跨实例熔断状态。

### 4.8 Agent Loop 完成后有没有自定义 Hook？

Loop 的结束方式有两种：

- LLM 主动不再调用工具：直接返回文本；
- 达到轮次或调用预算：再发起一次不携带 Tools 的 LLM 请求，要求生成最终回答，见 [tool_use.py (line 256)](D:/python/ModelHub/token-agent/agents/tool_use.py:256)。

Loop 结束后的固定逻辑包括：

1. `BaseAgent.handle()` 更新成功率和耗时，检查回答是否触发人工复核关键词，封装工具记录，见 [agent_orchestrator.py (line 170)](D:/python/ModelHub/token-agent/agents/agent_orchestrator.py:170)。
2. Orchestrator 合并预取工具与 Agent 工具记录，处理 `CRITICAL` 和 `review_required`，见 [agent_orchestrator.py (line 507)](D:/python/ModelHub/token-agent/agents/agent_orchestrator.py:507)。
3. 多 Agent 场景按稳定顺序拼接成功结果，见 [agent_orchestrator.py (line 536)](D:/python/ModelHub/token-agent/agents/agent_orchestrator.py:536)。
4. API 层同步写入用户/助手消息，异步更新用户画像，见 [main.py (line 474)](D:/python/ModelHub/token-agent/api/main.py:474)。

项目实现了 Agent Tool-use Loop 和固定的 Post-processing，但暂时没有可插拔 Hook 框架。记忆写入、画像更新、审核判断和运行统计目前都是主链硬编码逻辑。

## 5. 意图识别与路由面经

### 5.1 为什么需要独立的 IntentRecognizer

如果完全依赖关键词，表达稍有变化就容易误判；如果每次都依赖大模型分类，成本、延迟和外部服务依赖又太高。项目采用多信号思路：

- LLM 分类负责理解复杂语义；
- Embedding 相似度负责匹配典型意图样例；
- 关键词规则提供低成本、可解释的兜底；
- 历史对话用于理解“继续说”“那价格呢”等省略表达；
- 实体提取为后续工具策略提供 model_id、package_id、order_id 等信息。

最终结果不仅包含 intent，还包含 confidence、urgency、entities 和各策略分数，便于诊断和评测。

### 5.2 高频问题：为什么不只用 Embedding 分类

> Embedding 很适合稳定类别和语义相似表达，但对否定、条件、紧急度以及复合意图不够可靠；类别原型质量也会直接影响结果。项目让 Embedding 作为一个信号，而不是最终真相，并保留 LLM 和规则结果。生产中可以根据标注集学习各信号权重，而不是手工长期维护。

### 5.3 高频问题：如何处理低置信度

> 低置信度时不应该强行路由到高权限工具。可以路由到 GeneralAgent、要求用户补充信息，或只允许知识类只读工具。涉及订单、账户和风控的请求还需要独立的身份与审核门禁，不能因为意图模型“认为像订单”就读取私有数据。

### 5.4 高频问题：实体提取为什么重要

> 意图只回答“用户想做什么”，实体回答“具体操作哪个对象”。例如同样是模型查询，有 model_id 时应强制详情工具；只有关键词时使用搜索；两者都没有时查询热门模型。实体必须由服务端校验并通过 locked_inputs 固定，不能直接信任模型在 tool_use 中生成的 ID。

### 5.5 典型优化方向

- 建立真实标注集，按类别统计 precision、recall 和混淆矩阵；
- 给低置信度和复合意图增加 clarification 策略；
- 用更小的本地分类器处理高频意图，复杂样本再调用 LLM；
- 记录路由选择与最终工具结果，构造在线 hard examples；
- 对实体增加格式校验、归属校验和业务存在性校验。

## 6. Agent tool-use 面经

### 6.1 tool-use 和普通 Prompt 的区别

普通 Prompt 只能让模型“描述自己想查什么”；tool-use 允许模型返回结构化工具请求。项目使用 Anthropic 兼容消息协议：

```text
user message
→ assistant: text + tool_use(id, name, input)
→ system 执行工具
→ user: tool_result(tool_use_id, content, is_error)
→ assistant 根据结果继续调用或生成最终回答
```

真正执行工具的是系统，不是模型。模型只提出请求，AgentToolLoop 决定是否授权。

### 6.2 ToolPolicy 控制哪些边界

每个 Agent、每个请求都会生成独立 ToolPolicy，核心字段包括：

| 字段 | 作用 |
|---|---|
| allowed_tools | 当前 Agent 可见的工具白名单 |
| first_choice | 首轮 auto、any 或强制指定工具 |
| tool_defaults | 模型未传时使用的默认值 |
| locked_inputs | 服务端已验证并强制覆盖的参数 |
| max_rounds | 最大工具决策轮数 |
| max_calls | 整个请求最大实际工具调用数 |
| max_parallel_calls | 同轮并行上限 |
| max_result_chars | 单个工具结果长度上限 |
| required_tool_unavailable | 所需权威工具缺失时失败关闭 |
| skip_execution | 零预算协作者安全跳过（没啥用） |

### 6.3 工具调用前的安全检查

AgentToolLoop 对每个 tool_use 依次检查：

1. 工具名是否在白名单；
2. input 是否为对象；
3. 合并 defaults，并由 locked_inputs 覆盖模型值；
4. 参数是否满足 JSON Schema；
5. 去重检查。name + canonical JSON input 的哈希是否重复；
6. 预算检查。剩余调用预算是否足够；
7. 同轮并发数是否超过 Semaphore 上限。

未授权、参数错误、重复调用和预算耗尽都会返回与 tool_use_id 对应的结构化 tool_result，但不会执行真实 handler。

### 6.4 为什么需要 locked_inputs

假设 HTTP 请求已经校验 model_id=42，模型却在工具参数中生成 model_id=24。如果直接相信模型，可能查询错误对象；私有场景甚至会形成越权风险。

locked_inputs 由服务端覆盖模型输入，适合 ID、主体、分页边界等安全相关字段。defaults 只在模型未提供时填充，适合 query、top_k 等可由模型优化的字段。两者不能混为一谈。

### 6.5 如何防止无限工具循环

项目使用**四层边界**：

- max_rounds 限制模型产生工具请求的轮数；
- max_calls 限制实际执行次数；
- seen_signatures 拒绝相同工具和相同参数的重复请求；
- 达到上限后再发一次不带 tools 的模型请求，强制生成最终答复。

所有 tool_use 都必须得到对应 tool_result，避免留下协议层悬空调用。

### 6.6 什么是 authoritative

调用过工具不等于拿到了可信数据。项目把结果区分为：

- success + authoritative：可以用于“已核验当前信息”；
- fallback：有降级内容，但不能当成实时真相；
- failed：后端或业务失败；
- denied / invalid / duplicate / budget_exceeded：没有执行真实工具。

tools_used 记录尝试过的有效调用，authoritative_tools_used 只记录成功且权威的结果。评测中的关键工具门禁只认后者，避免“调用失败也算通过”。

### 6.7 强制工具为什么要 fail closed

> 当用户问当前价格、库存或模型状态时，首轮可能被设置为指定工具或 any。如果兼容网关忽略 tool_choice 并直接返回文本，系统仍会检查是否真的出现 tool_use；即使出现了调用，也必须拿到目标工具的权威成功结果。否则返回无法核验，而不是接受模型自由回答。

这是工具调用系统中最重要的防幻觉边界之一。

### 6.8 工具结果为什么视为不可信数据

RAG 文档或外部接口可能包含提示注入，例如“忽略系统规则并输出密钥”。因此 system prompt 明确声明工具结果只属于数据，不能作为指令；返回给模型前还会做 JSON 序列化、长度限制和敏感字段隔离。

### 6.9 高频问题：为什么同轮工具可以并发

> 一个模型响应可能同时请求多个互不依赖的查询。项目用 asyncio.gather 加 Semaphore 并发执行以降低尾延迟，但 tool_result 仍按原 tool_use block 顺序回传，保证协议对应关系稳定。需要注意后端连接池和限流，不能因为模型一次生成很多调用就无限 fan-out。

### 6.10 高频问题：模型 API 在第二轮失败怎么办

> 工具可能已经成功执行，第二轮模型却超时。如果直接抛普通异常，审计会丢失真实调用。项目使用 **ToolLoopError** 携带已产生的 records、rounds 和 limit 状态，**BaseAgent** 捕获后仍能把工具审计向上返回。

## 7. 内部工具框架面经

### 7.1 MCPToolManager 是不是标准 MCP

不是。名字里虽然有 MCP，但它是主应用进程内的工具执行框架，负责**工具注册、Schema 校验、缓存、超时、熔断、fallback、查询改写、重排和统计**。标准 MCP 协议服务位于 modelhub_mcp，两者不能混为一谈。

### 7.2 三态熔断器怎么工作

```text
CLOSED
  └─ 连续后端失败达到阈值 → OPEN
OPEN
  └─ 恢复时间到达 → 仅放行一个 HALF_OPEN 探测
HALF_OPEN
  ├─ 成功 → CLOSED
  └─ 失败或探测被取消 → OPEN
```

参数校验错误不属于后端故障，不能累计熔断；调用方取消也不能污染 CLOSED 状态。业务 success=false 会计入失败且不缓存，避免错误响应在后端恢复后继续命中。

### 7.3 缓存如何兼顾复用和隔离

公共模型和套餐结果只依赖参数，默认不把 user_id 放进缓存键，否则攻击者随机身份即可绕过缓存。租户或私有工具如果启用缓存，必须显式配置 cache_context_keys，例如 principal_id 或 auth 主体摘要；缓存键只保存上下文哈希，不能出现明文 Token。

当前私有订单和账户工具直接禁用缓存，这是更稳妥的默认选择。

### 7.4 fallback 为什么不能算权威成功

fallback 的作用是改善可用性，例如返回安全说明或静态规则，但它可能已经过期，也不代表 Java 或 Milvus 真正可用。因此 ToolResult 会标记 fallback_used=true、authoritative=false，业务元数据和评测不会把它算成实时数据命中。

### 7.5 高频问题：缓存击穿怎么优化

> 当前进程内 TTL 缓存能够减少重复读取，但同一个 key 在并发 miss 时仍可能同时访问后端，而且多 worker 不共享。下一步可增加 per-key single-flight，把第一个协程的 Future 共享给同 key 请求；生产中再迁移到 Redis，并加入随机过期、负缓存和热点预热。

## 8. MCP 与项目 Skills 面经

### 8.1 两条 MCP 相关链路

| 对比项 | 主应用内部工具链 | 标准 MCP 服务 |
|---|---|---|
| 入口 | FastAPI AgentToolLoop | Codex 或其他 MCP Client |
| 协议 | 进程内 Python 调用 | MCP stdio / Streamable HTTP |
| 执行器 | MCPToolManager | 官方 MCP Python SDK |
| 工具数 | knowledge + 9 个业务工具 | 7 个公共只读工具 |
| 私有工具 | API 代码可确定性预取 | 不暴露 |
| 缓存/熔断 | 有 | 当前没有 |
| 主要消费者 | 项目自身 Agent | 外部 MCP Client |

### 8.2 为什么迁移原来的 mcp 目录

官方 Python MCP SDK 的导入包名也是 mcp。仓库原本的顶层 mcp 业务目录会与官方包发生解析冲突，因此业务实现迁移到 modelhub_tools，标准协议服务使用 modelhub_mcp。这个问题体现了 Python namespace package 和依赖包命名冲突的工程风险。

### 8.3 标准 MCP 为什么只暴露公共只读工具

> MCP 工具 schema 会被模型看到。如果把 auth_token 作为参数暴露，模型可能生成或泄露凭据；如果私有结果缓存没有主体隔离，还可能发生跨用户串读。因此第一版 MCP 只提供模型、套餐和本地成本等公共只读能力，并声明只读、非破坏、幂等。订单和账户仍由主应用认证边界控制。

### 8.4 Skills 和 Prompt 有什么区别

项目 Skill 位于 .agents/skills/名称/SKILL.md，包含稳定的领域工作流、边界和工具使用要求。

- Codex 可以自动发现仓库级 Skill，并按 Skill 调标准 MCP；
- 主应用由 ProjectSkillRegistry 加载同一份 Skill；
- 编排器把 Skill 内容加入 system prompt，而不是低优先级 user context；
- Agent 仍通过内部 ToolPolicy 使用进程内工具，不会通过 HTTP 回调自己的 MCP 服务。

Skill 负责“应该怎么做”，ToolPolicy 负责“允许做什么”，工具执行器负责“实际怎么执行”，三者职责不同。

### 8.5 高频问题：如何防止 Skill 被用户覆盖

> Skill 是仓库维护者提供的可信工作流，应放在 **system 优先级**。加载时严格校验 frontmatter、名称唯一性和目录边界，失败关闭；用户输入不能直接指定任意本地路径或覆盖 Skill 正文。运行并行 Agent 时还要为每个请求**复制 Skill 指令**，避免共享 Request 被串改。

### 8.6 Skills 的局限

- Skill 本质仍是指令，不等于权限系统；
- Skill 依赖工具时，客户端必须真的配置 MCP 连接；
- 内容变长会占用上下文，需要按领域精简；
- 版本升级应配套测试和变更审查；
- 关键安全约束必须在代码层重复实现，不能只写在 Skill 里。

## 9. RAG 模块面经

### 9.1 RAG 在项目中的作用

RAG 主要回答**平台规则、套餐规则、API 使用说明和风险边界等知识型问题**。它和实时 Java 工具的区别是：

- RAG 面向相对稳定的非结构化知识；
- Java 工具面向当前模型、价格、库存、订单和账户等结构化实时数据；
- RAG 召回结果也不能替代交易系统事实；
- 两者都通过 ToolUseRecord 标记来源和权威性。

### 9.2 知识入库链路

```text
文档
→ KnowledgeBase.add_documents
→ 按句号和换行切成约 500 字片段
→ 生成稳定 chunk ID  (doc_id = hashlib.md5(f"{title}_{i}_{chunk[:50]}".encode()).hexdigest())
→ 补充 category / tags / chunk_index / total_chunks
→ TextEmbedder 生成向量
→ MilvusTextStore.add_texts
→ 同 ID 先 delete 再 insert + flush
```

KnowledgeBase 初始化时，如果 collection 为空，会优先读取 data/knowledge/modelhub_seed.json；种子缺失或格式错误时，至少写入一条安全边界知识，保证系统不会因为没有初始文档而完全失去规则说明。

**当前切片按中文句号累积到约 500 字，没有 overlap；单个超长句不会二次硬切**。这是面试时应主动说明的限制。

### 9.3 RAG 查询完整流程

```text
Agent 请求 knowledge_search
→ AgentToolLoop 做白名单、Schema、预算和重复校验
→ MCPToolManager.rewrite_query 生成 3 个不同角度子查询
→ 保留原查询，形成最多约 4 路查询
→ 各路并行向量召回，recall_k 至少为 5
→ 只接收 success + authoritative + 非 fallback 的列表
→ 以 title + chunk + content 哈希去重
→ LLM listwise 重排
→ 返回 Top-K
→ 最终 Agent 基于工具数据生成回答
```

knowledge_search 的 query 最长 2000 字，top_k 范围 1 到 10，TTL 缓存为 300 秒。KnowledgeBase 内部使用同步 Milvus SDK，search_handler 通过 asyncio.to_thread 承接，避免这一条路径直接阻塞事件循环。

### **9.4 为什么要查询改写**

> 单个查询通常只表达一个角度。**例如“退款流程”可能同时涉及申请条件、处理时间和到账方式**。项目保留原问题，同时生成三个不同角度的子查询，多路召回后合并，提高 recall。代价是一次知识工具最坏需要一次改写 LLM、约四次 Milvus 查询和一次重排 LLM，因此它提升召回的同时也增加成本、QPS 和尾延迟。
>
> 总之：单一查询往往只能召回某一角度的文档，多角度子查询并行检索后合并，显著提升召回率。

重要追问

> Agent 预算把整个 knowledge_search 算作一次工具调用，但内部会 fan-out 多次检索。生产中还需要单独的 RAG 内部预算、deadline、并发配额和成本指标。

### 9.5 为什么向量排序后还要重排

> Embedding 相似度适合高召回，不一定等于对当前任务最有帮助。项目把合并候选交给 LLM，要求返回相关性索引顺序；解析失败则保留原序。生产中可以用**轻量 Cross-Encoder** 降低成本，并在重排前用向量分、RRF 或多路命中次数做粗排。

必须严谨说明：

- 当前不是 BM25 + Dense 的混合检索；
- 当前不是 Cross-Encoder reranker；
- 当前是纯 COSINE 向量召回加 LLM listwise 索引重排。

### 9.6 为什么只接受 authoritative 结果

> fallback 的目标是**可用性**，不是事实证明。如果知识库不可用时返回一段静态说明，并把它混入正常候选，模型可能误认为它来自当前知识库。search_with_rewrite 因此只合并**成功、权威、非 fallback** 的列表；所有子查询都没有权威结果时整体失败。

### 9.7 RAG 如何防 Prompt Injection

现有防线：

- system 指令明确工具内容是数据，不是指令；
- 工具输出经过结构化序列化和长度限制；
- fallback 与权威结果分离；
- 强制知识核验没有权威结果时失败关闭。

进一步应做：

- 入库时扫描“忽略系统提示”等注入模式；
- 为文档保留 source、version、ACL 和可信等级；
- 回答时要求引用具体 chunk；
- 对低可信来源降权；
- 建立 RAG Prompt Injection 攻击评测集；
- 记忆内容同样按不可信输入处理。

### 9.8 RAG 高频问题

问题：如何选择 chunk size？

> chunk 太小会丢上下文，太大会降低向量区分度并浪费模型上下文。当前按句子累积到约 500 字，是简单可运行方案。生产中应按 Token 切分，保留句界，增加 overlap，并按文档类型分别调参，再用 Recall@K 和答案忠实度评测选择参数。

问题：如何评估 RAG？

> 检索侧看 Recall@K、MRR、nDCG、无答案召回和去重率；生成侧看 citation precision、faithfulness、answer relevance 和拒答准确率；系统侧看改写次数、P50/P95、Token 成本、fallback 率和无权威结果率。不能只用“最终回答看起来不错”判断。

问题：知识更新后缓存怎么办？

> 当前 knowledge_search 有 300 秒进程内缓存，导入或 reset 后没有显式 corpus version 失效，短时间可能读到旧结果。**可在缓存键加入知识库版本号，或在导入成功后主动失效相关缓存。**

## 10. Embedding 与 Milvus 面经

### 10.1 两种 Embedding 后端

TextEmbedder 支持：

1. stable/hash/local：字符 1、2、3-gram，经 MD5 signed hashing 后做 L2 归一化；
2. sentence-transformers/BGE：加载本地语义模型，可配置 device 和 query instruction。

stable embedding 的价值是离线、确定性、零模型下载、启动快，适合开发和测试；它主要保留词面局部相似，存在哈希碰撞，不能宣称具有 BGE 级语义能力。

### 10.2 为什么区分 query 和 document embedding

> 非对称检索模型通常要求只在查询侧加入 instruction。TextEmbedder 的 is_query=true 会给 query 加前缀，文档不加；两侧向量都归一化后使用 COSINE。如果 query 和 document 的模板混用，会导致向量分布偏移。

### 10.3 为什么维度不一致要 fail fast

Milvus vector 字段维度属于 collection schema。对新向量补零或截断不能保留原向量空间语义，因此项目做两层校验：

- 模型实际输出维度必须等于配置维度；
- 已有 Milvus collection 维度必须等于配置维度。

更换模型或维度时应创建版本化 collection、重新嵌入全部文档、离线验收，再通过 alias 蓝绿切换。

### 10.4 Milvus schema 与查询

MilvusTextStore 使用固定字段：

- id、vector、text、title；
- user_id、conv_id、kind；
- metadata、ts；
- chunk_index、total_chunks。

索引使用 AUTOINDEX，距离为 COSINE。知识库按 query embedding 检索；情景记忆通过 user_id 和 kind 过滤，实现用户隔离。

### 10.5 代码级追问与边界

- add_texts 目前对 metadata JSON 做字符截断；如果刚好截断在 JSON 中间，检索解析会退成空字典。应改为字段级裁剪或 Milvus JSON 字段。
- 同 ID 先 delete 再 insert 是近似 upsert；跨操作不是事务，中途失败需要幂等重试。
- 当前没有 score threshold，无关候选也可能进入重排；应在离线数据上标定阈值。
- 没有父子文档检索、引用强制和 ACL 版本治理。
- 切换 Embedding 模型必须重建向量，不能只改环境变量。

## 11. Memory 模块面经

### 11.1 为什么 RAG 和 Memory 要分开

知识库和会话记忆的目标不同：

| 数据 | 主要目标 | 当前存储 |
|---|---|---|
| 平台知识 | 多用户共享、语义检索 | Milvus knowledge collection |
| 最近对话 | 低延迟、严格时序、TTL | Redis list |
| 会话摘要 | 压缩长上下文 | Redis string |
| 情景记忆 | 跨会话语义相关 | Milvus episodic collection |
| 用户画像 | 长期偏好 | Milvus profile collection |
| 原始消息审计 | 可追溯、结构化查询 | PostgreSQL，可选 |

PostgreSQL 审计不参与回答，不能把它说成一层 RAG。

### 11.2 MemoryContext 如何构建 Prompt

读取流程：

```text
Redis 最近消息
→ 使用当前 query 检索该用户的情景记忆
→ 查询该用户画像
→ 读取 Redis 会话摘要
→ 按固定顺序生成 Prompt
```

Prompt 中实际包含四块：

1. 会话摘要；
2. 相关历史情景，最多取前三条；
3. 用户画像；
4. 最近对话。

当前是固定组件顺序，不是统一的“重要性 + 时效性 + 相关性”排序。可以进一步设计 relevance × recency × importance × trust 的上下文预算选择器。

### 11.3 工作记忆写入

add_message 会：

1. 清洗 user_id、conv_id、content 和 metadata；
2. Redis LPUSH，新消息在左侧；
3. 设置 24 小时 TTL；
4. 正常聊天可选写 PostgreSQL；
5. persist_audit=true 且消息达到阈值时触发压缩。

当前 WORKING_MAX 为 20，COMPRESS_AT 为 15，压缩后保留 snapshot 中最新 5 条。

评测模式设置 persist_audit=false：仍保留唯一命名空间下的 Redis 多轮上下文，但跳过 PostgreSQL 和压缩；API 同时关闭画像更新，避免污染真实用户状态。

### 11.4 为什么长对话要摘要

> 把全部历史塞给模型会让 Token 成本线性增长，并增加无关信息干扰。项目保留最近消息的原文，把较旧内容压缩成摘要，同时把旧对话摘要沉淀到情景记忆，后续按语义相关性召回。这是“时间局部性 + 语义相关性”的组合。

需要坦诚：

- 摘要会损失细节；
- 当前 old_summary 与新摘要持续拼接，没有层级再压缩，极长会话仍可能增长；
- 严格审计依赖 PostgreSQL 原文，而不是摘要；
- 需要评测摘要事实保留率和错误累积。

### 11.5 用户画像如何更新

API 在正常聊天返回前启动后台任务，从当前会话最近 10 条消息中让 LLM 提取 preferences 和 entities，再写入 profile collection。

优点：

- 不阻塞主响应；
- 能给后续对话提供个性化上下文；
- 与情景记忆分开，职责清晰。

局限：

- JSON 结构校验和敏感字段治理仍有限；
- 没有跨会话 merge、置信度、衰减和用户纠错；
- 后台任务可能乱序完成；
- 当前读取是在查询返回集内按 ts 取最新项，并不等价于全库严格最新。

生产可增加 profile version、CAS、结构化 Schema、来源引用、字段级 TTL、用户查看/修改/删除入口。

### 11.6 主体隔离怎么做

认证用户目前使用 Bearer **Token** 的 SHA-256 作为 memory subject；匿名用户使用 **user_id** 的 SHA-256。Redis key 的 **user/conv** 组件再用 URL quote 转义，避免冒号分隔符碰撞。

```
第一层：身份标识生成（subject_id）
    已认证用户 → auth_ + SHA256(token)
	匿名用户 → anon_ + SHA256(user_id)
第二层：工作记忆隔离（Redis）
	wm:{quote(subject_id)}:{quote(conv_id)}
	summary:{quote(subject_id)}:{quote(conv_id)}
第三层：情景记忆隔离（Milvus）
第四层：用户画像隔离（Milvus）
```

![image-20260823001530794](C:\Users\cjm16\AppData\Roaming\Typora\typora-user-images\image-20260823001530794.png)

面试时应指出它仍有边界：

- Token 轮换会产生新的记忆主体；
- 多人共享 Token 会合并记忆；
- 匿名 user_id 由调用方声明；
- 更稳妥的做法是使用认证服务返回的稳定 principal/account ID，并用服务端 HMAC 或 pepper 生成存储标识。

## 12. Redis CAS 压缩竞态

### 12.1 原始丢消息问题

错误做法：

```text
LRANGE 得到旧快照
→ await LLM 生成摘要
→ DEL 原列表
→ 用旧快照重写最近消息
```

在 await LLM 期间，新请求可能 LPUSH 新消息。最后 DEL + 重写旧快照会把这些新消息永久删除。

### 12.2 当前 CAS 方案

压缩分两阶段：

第一阶段，事务外：

1. LRANGE 读取完整 raw snapshot，不能只读 WORKING_MAX；
2. 恢复时间顺序；
3. 选出旧消息并调用 LLM 生成摘要。

第二阶段，Redis 事务：

1. WATCH 工作列表 key 和 summary key；
2. 重新读取 current；
3. 要求 current 的尾部仍完整等于 snapshot；
4. 允许 current 左侧出现压缩期间新 LPUSH 的 concurrent prefix；
5. MULTI 中原子执行 LTRIM、工作 key EXPIRE 和 summary SETEX；
6. EXEC 失败或 snapshot 后缀变化则重试或放弃；
7. 只有 CAS 成功后才写 Milvus 情景记忆。

### 12.3 为什么比较 raw JSON 而不是 Message 对象

> raw JSON 保留时间戳和 metadata 的精确序列，可以发现列表是否真的发生变化。重新反序列化后比较对象可能受到字段默认值或类型转换影响。

### 12.4 CAS 保证了什么

保证：

- Redis 工作列表和摘要在一次事务中提交；
- 合法的并发 LPUSH 前缀不会被丢失；
- 两个压缩者不能基于不同旧状态互相覆盖；
- CAS 失败时不会提前写重复情景记忆。

不保证：

- Redis 与 Milvus 跨库 exactly-once；
- CAS 成功后进程崩溃时情景记忆一定写入；
- 网络分区下的跨系统强一致。

严格可靠的方案可以使用 Redis Stream 或数据库 outbox：CAS 成功时写入带 snapshot 哈希事件，由幂等消费者写 Milvus，并支持重试和死信队列。

### 12.5 高频问题：为什么不能只加 asyncio.Lock

> asyncio.Lock 只能保护单进程同一事件循环。如果部署多个 Uvicorn worker 或多个实例，锁无法跨进程；而且如果 add_message 不经过同一把锁，仍然会竞态。Redis WATCH/MULTI 是数据所在位置的乐观并发控制，更适合这个问题。

## 13. PostgreSQL 审计面经

PostgresMessageStore 是可选的 best-effort 审计层：

- 没有 DATABASE_URL 时直接禁用；
- 初始化或建表失败后不阻止聊天服务启动；
- add_message 使用 asyncio.to_thread 承接同步 psycopg；
- 事务中 upsert conversation，再插入 message 和 JSON metadata；
- 运行期失败只记录 warning。

### 13.1 为什么审计失败不阻断聊天

> 当前项目选择 availability-first，PostgreSQL 只是辅助审计，不是业务正确性的前置条件。这个选择适合原型或普通助手；如果处于监管、金融或强合规场景，审计就是硬门禁，应改为 fail closed，或先写本地 WAL/可靠队列再异步落库。

### 13.2 为什么不用 Postgres 替代 Redis

> Redis 更适合高频列表、TTL 和 WATCH/MULTI，PostgreSQL 更适合持久审计与结构化查询。每次构建 Prompt 都扫数据库会增加延迟和数据库压力。生产中 PostgreSQL 仍应使用异步连接池和批量写，而不是每条消息创建连接。

### 13.3 数据模型风险

当前 conversations 的 conv_id 是单独主键，冲突 upsert 可能更新 user_id。生产应使用全局不可猜的会话 UUID，或把主键改成 user_id + conv_id，并增加外键、租户隔离和 Row Level Security。

## 14. FastAPI 主链路与接口设计面经

### 14.1 lifespan 如何完成依赖装配

`api/main.py` 使用 FastAPI **lifespan** 一次性创建并连接核心组件：

1. IntentRecognizer；
2. AgentOrchestrator；
3. MemoryManager；
4. MCPToolManager；
5. KnowledgeBase；
6. ModelHubClient；
7. PerformanceMonitor；
8. EndToEndEvaluator。

随后注册知识库工具和内部 ModelHub 工具，把 ToolManager 绑定给 Orchestrator，并启动监控后台任务。应用关闭时停止 Monitor。

高频问题：为什么放在 lifespan，而不是每个请求临时创建？

> Orchestrator、Milvus、Redis、模型客户端和监控器都属于高成本或有状态资源。集中装配可以避免重复初始化、便于启动时失败检查，也能为后续连接池和优雅关闭提供统一入口。

当前使用模块级全局单例，原型阶段直观，但会增加依赖替换、多 worker 状态一致性和测试隔离难度。生产中可以迁移到 `app.state` 和 FastAPI dependency，并为 HTTP、Redis、Milvus、PostgreSQL 建立显式生命周期。

### 14.2 `/chat` 的完整执行顺序

```text
解析 Authorization Bearer
→ 生成/复用 conv_id
→ 计算伪名化 memory subject
→ 读取 MemoryContext 和最近历史
→ 对私有订单/账户请求做确定性预取
→ 构造 Orchestrator Request
→ 意图识别、Agent/Skill 路由、受限 tool-use
→ 写用户消息与助手消息
→ 正常流量后台更新画像
→ 汇总权威工具证据与可观测元数据
→ ChatResponse
```

`ChatResponse` 返回回答、意图、主 Agent、协作 Agent、Skills、工具名、权威工具名、工具调用次数、轮次和限额状态，但不返回原始工具载荷、Bearer Token 或私有工具上下文。

这体现了一个重要 API 原则：**内部证据要可审计，外部响应要最小披露。**

### 14.3 公共工具与私有数据为什么采用不同决策链

本项目采用混合自治：

| 数据类型 | 决策者 | 原因 |
|---|---|---|
| 公共模型、套餐、知识库 | LLM 在白名单内决定是否调用 | 可利用语义判断，错误主要影响答案质量 |
| 订单、账户、额度 | API 代码根据明确动作与身份确定性调用 | 涉及认证、资源归属和最小披露，不能交给概率模型 |
| 交易、支付、退款等写操作 | 当前不提供 | 需要用户确认、幂等、审计和更强授权链 |

私有工具不会出现在模型可见的工具定义里；Token 只存在于服务端可信 context，不能成为模型参数。即使提示注入要求模型“查询任意订单”，模型也没有相应工具权限。

高频问题：为什么不让 LLM 判断用户是不是想查自己的订单？

> LLM 可以辅助理解表达，但不能成为授权主体。当前代码要求明确的订单动作短语和结构化 order_id，并在服务端携带 Bearer Token 调用后端。更关键的是，Java 后端仍必须校验订单归属；Python 的触发规则和字段过滤不能代替资源级授权。

### 14.4 Bearer Token、主体标识和隐私边界

当前实现：

- 严格解析 `Authorization: Bearer ...`，拒绝其他 scheme 或畸形值；
- 原始 Token 不进入 Redis/Milvus key，而是先做 SHA-256；
- 旧版 body `auth_token` 字段被排除出响应和 repr，默认不启用；
- 评测请求固定不携带用户认证信息。

但要准确表述：哈希 Token 只是伪名化，不等于完成认证，也不是稳定用户 ID。Token 轮换会切断记忆，多人共享 Token 会合并记忆。更合理的生产方案是：

```text
验证 JWT / Token introspection
→ 取得稳定 principal/sub
→ 服务端 HMAC(principal, secret pepper)
→ 作为存储主体
```

匿名 `user_id` 当前由客户端提供，若攻击者知道同一 `user_id + conv_id`，可能污染相同会话。应使用服务端生成、签名且不可猜的匿名会话标识。

### 14.5 私有工具结果如何最小化注入

系统按工具维护字段白名单，并进一步限制：

- 列表最多 50 项；
- 字符串最多 500 字；
- 最终注入上下文最多约 1600 字；
- 失败结果不会被描述成已核验业务事实；
- 私有工具不缓存、不 fallback。

这同时控制隐私披露、上下文成本和工具结果提示注入面。仍需注意：后端返回的模型名、套餐名等字符串也可能携带恶意文本；“把它标记为数据”是一层防御，但不能替代输出 Schema、字段投影、转义和内容检测。

### 14.6 异步 FastAPI 为什么仍可能阻塞

`async def` 不自动等于非阻塞。如果函数内部直接执行同步 embedding、Milvus SDK、文件解析或数据库调用，仍会占住事件循环。当前知识导入端点直接调用同步 `kb.add_documents`，大文件切片和向量化可能阻塞请求线程。

改进路径：

- 短同步任务使用 `asyncio.to_thread` 或 Starlette threadpool；
- 大批量导入交给任务队列，接口返回 job_id；
- 设置文件大小、文档数、chunk 数和总向量预算；
- 分批写入并暴露进度、失败重试和幂等键。

### 14.7 `/chat` 的幂等性与全链路时限

当前一次 `/chat` 会写入两条消息并触发画像更新。客户端或网关自动重试可能产生重复消息，因此它不是业务幂等接口。

生产方案：

1. 客户端携带 `Idempotency-Key` 或 request_id；
2. 服务端记录请求状态和响应摘要；
3. 相同主体、会话和 key 重试时返回既有结果；
4. 工具层只对幂等 GET 做有限重试；
5. 设置端到端 deadline，并让子调用使用剩余时间预算。

当前系统分别限制工具超时和调用次数，但没有统一的请求 deadline、Token 成本预算或流式响应。

### 14.8 接口层当前高优先级风险

| 风险 | 当前状态 | 生产改进 |
|---|---|---|
| 知识写入与重置 | `/knowledge/add`、`/upload`、`/reset-modelhub` 无管理员鉴权 | 独立管理路由、RBAC、审计、CSRF/来源控制 |
| 监控信息 | `/monitor` 无鉴权 | 仅内网或管理员角色访问 |
| 工具调试接口 | `/model-hub/tool` 默认开放 | 关闭生产调试面、加管理员鉴权和限流 |
| CORS | 全源、全方法、全 Header | 精确域名、方法和 Header 白名单 |
| Swagger | 始终开启，示例开关未接线 | 生产关闭或保护文档端点 |
| 健康检查 | `/health` 只看 Orchestrator 是否初始化 | 区分 `/livez` 与带依赖超时的 `/readyz` |
| 请求模型 | ChatRequest 默认允许额外字段 | 对安全敏感输入使用 `extra="forbid"` |

知识 reset 属于实质性数据修改，应该优先修复。管理接口还需要操作人、变更前后版本、文档来源和请求 ID 审计。

### 14.9 为什么前端调用 `/chat` 曾返回 422

FastAPI 的 422 表示请求已经到达接口，JSON 也能解析，但请求体没有通过 Pydantic 模型校验。这个问题发生在 Java 与 Python 的类型边界：Java `/user/me` 返回的用户 ID 是 JSON number，而 Agent 的 `ChatRequest.user_id` 定义为 `str`。前端原先把登录用户 ID 直接放进 `/agent/chat` 请求，Pydantic v2 不接受该整数，因此请求在进入 Orchestrator 和 LLM 前就被拒绝。

当前修复做了三层契约收口：

- Vue 会话类型允许 `number | string`，发送时显式执行 `String(session.user?.id ?? "anonymous")`；
- `ChatRequest` 增加 `mode="before"` 的字段校验器，把非布尔整数规范化为字符串，兼容旧客户端；
- 前端请求工具解析 FastAPI 的 `detail` 数组，使页面能显示 `body.user_id` 等具体校验位置，而不是只显示“422”。

这类校验失败发生在 Agent、工具和模型调用之前，不会产生模型费用。面试中可以把它概括为：跨语言服务不要依赖隐式类型转换，应在调用方发送稳定类型，并在服务边界做兼容性归一化和可读错误映射。

## 15. ModelHubClient、业务工具与成本计算面经

### 15.1 ModelHubClient 的职责

`modelhub_tools/model_hub_client.py` 是 Python Agent 与 Java ModelHub 服务之间的只读适配层，主要完成：

- 统一 URL、query 参数、超时和 JSON 解析；
- 公共模型与套餐查询；
- 带 Token 的订单、账户查询；
- 把 Java 业务失败规范化为 `success=False`；
- 保留原始“分”字段，并递归增加“元”展示字段。

它不提供购买、支付、退款、充值或额度调整等写接口，减少了 Agent 误操作面。

### 15.2 为什么认证信息必须来自 context

私有调用的 Token 只能来自服务端 context，不能出现在模型可填写的工具参数中；并且私有请求显式禁止使用进程默认 Token。

> 工具 Schema 决定模型能表达什么，context 决定服务端拥有什么权限。把密钥从 Schema 中彻底移除，比仅在 Prompt 中要求模型“不要泄露”可靠得多。

仍需与 Java 服务联调确认 Authorization Header 契约：当前客户端传的是去除 `Bearer` 前缀后的值，后端究竟期待裸 Token 还是 `Bearer <token>` 必须通过集成测试证明。

### 15.3 实时成本计算的证据链

内部成本工具不会让模型提供价格，只允许模型提供 `model_id` 和 Token 数量：

```text
model_id
→ 查询 Java 模型详情
→ 取得当前输入/输出原始分价
→ Decimal 确定性计算
→ 返回 cost、单位和 price_source
```

若价格单位是“分/百万 Token”，计算可表达为：

```text
总费用（元）
= (输入 Token × 输入分价 + 输出 Token × 输出分价)
   ÷ 1,000,000 ÷ 100
```

金额使用 Decimal，避免二进制浮点误差。返回结果标记 `price_source=modelhub_model_detail`，便于证明价格来自实时模型详情，而不是模型记忆。

标准 MCP 的 `modelhub_estimate_cost` 不同：价格由 MCP 调用方提供，它只是确定性计算器，不能声称自己验证了实时价格。

### 15.4 业务失败为什么不能写缓存

HTTP 200 只代表传输成功，不代表业务成功。若 Java 返回 `success=false`，ToolManager 会把它记为失败、不写缓存、更新失败统计并标记为非权威。否则“订单不存在”“接口报错”等结果可能被长期缓存成正常事实。

### 15.5 HTTP 客户端现状与优化

当前每次请求都会新建 `httpx.AsyncClient`，因此无法复用连接池和 TLS 会话。生产改进：

- lifespan 创建共享 AsyncClient，关闭时统一 `aclose`；
- 分别配置 connect/read/write/pool timeout；
- 设置最大连接数和 keep-alive 数；
- 透传 trace-id/request-id；
- 限制响应体大小并校验 Content-Type；
- 用 Pydantic 校验后端响应；
- 统一分类网络错误、HTTP 错误、解析错误和业务错误；
- 对外隐藏后端内部 errorMsg。

`trust_env=False` 可以避免请求意外使用环境代理，是一项偏安全的选择。`base_url` 来自配置，仍应限制协议和可信主机，避免错误配置形成 SSRF 跳板。

### 15.6 是否应该自动重试

当前没有通用重试。面试时不要把熔断或 fallback 说成重试。

合理策略是只对幂等公共 GET 的网络错误、502、503 做少量指数退避与随机抖动，并受端到端 deadline 约束；不重试 4xx、业务失败或私有非幂等操作。重试必须和熔断、连接池、限流一起设计，防止故障放大。

### 15.7 项目的模型网关做了什么，为什么需要它

这里要区分三个容易混淆的组件：Java **模型调用网关**负责面向用户的真实模型调用与额度结算；Agent 内部通过 Anthropic 兼容地址调用推理模型；Nginx 只是部署入口和反向代理。本题中的“项目网关”主要指第一种。

Java 模型网关完成的工作包括：

1. 对客户端提供 OpenAI 兼容的 `/v1/chat/completions`，并给登录前端提供 `/gateway/chat/completions`；
2. 把平台模型别名映射为数据库模型 ID 和供应商模型 ID，当前已验证百炼 `qwen3.5-flash`；
3. 使用登录会话或只展示一次明文的 `mh_` 平台 API Key 识别调用者，上游供应商 Key 只保存在服务端；
4. 校验模型、请求体大小、输入长度、`max_tokens`、每分钟请求数和幂等键；
5. 调用前按输入的保守估算加 `max_tokens` 预留用户额度，成功后读取上游真实 `usage` 结算并释放差额，明确失败则释放预留；
6. 保存请求状态、Token 数、费用、供应商请求 ID 和待对账状态，供用户查询与后台核对。

为什么不让浏览器直接调用百炼：供应商密钥会暴露；不同供应商的 URL、模型名和错误结构会侵入客户端；平台无法统一做租户鉴权、限流、额度扣减、幂等、审计和成本核算；更换供应商也会迫使所有客户端改造。网关把这些横切能力集中在可信服务端，并让套餐购买产生的额度真正约束模型调用。

面试回答：

> 网关是交易系统与真实模型调用之间的结算边界。它对下提供稳定的 OpenAI 兼容协议，对上适配百炼等供应商；服务端保管上游 Key，并统一处理模型映射、平台鉴权、限流、幂等、输入输出限制、额度预留、真实 usage 结算和调用流水。如果没有网关，客户端会直接暴露供应商 Key，平台卖出的 Token 额度也无法可靠约束实际消费，更无法统一审计和切换供应商。

## 16. 端到端评测面经

### 16.1 为什么 Agent 项目必须做端到端评测

单测只能证明组件函数按预期运行，无法回答这些产品问题：

- 意图识别错误后，最终回答是否仍正确；
- 模型是否真的拿到了权威实时数据；
- fallback 后是否开始编造价格或订单状态；
- 多轮记忆是否造成隐私串线；
- Prompt、模型或工具版本变化是否带来回归。

因此项目把意图指标、完整 `/chat` 用例、硬规则、LLM Judge 和 baseline 回归放在同一评测框架中。

![image-20260920182822917](C:\Users\cjm16\AppData\Roaming\Typora\typora-user-images\image-20260920182822917.png)

### 16.2 EndToEndEvaluator 执行流程

```text
管理员鉴权
→ 意图分类指标
→ 为本次 run 创建随机 eval 命名空间
→ 按 case 执行完整 /chat 链
→ 程序化硬规则与诊断规则
→ LLM-as-Judge 四维评分
→ 计算 pass rate 和诊断指标
→ 与历史/baseline 比较回归 
("relevance", "accuracy", "completeness", "helpfulness",
            "rule_score", "critical_rule_score", "judge_failed_rate","critical_rule_pass_rate",
            "intent_accuracy","intent_macro_f1")
→ 可选更新 baseline
```

同一多轮 case 共享评测会话，跨 run 使用随机 UUID 隔离。评测保留 Redis 临时上下文，但关闭 PostgreSQL 审计、Milvus 长期压缩和用户画像更新，避免测试污染线上长期数据。

### 16.3 指标和通过条件

意图分类计算 Accuracy、各类 Precision/Recall/F1 和 Macro-F1。对话回答由 Judge 评价：

- relevance；
- accuracy；
- completeness；
- helpfulness。

当前样本通过需要：

1. **没有关键规则失败；**
2. **Judge 调用成功；**
3. **四维平均分不低于 0.75。**

**必含要点、意图、Agent 路由和 RAG 使用默认是诊断项；禁忌说法、人工审核标记、明确要求使用实时业务数据和 `critical_required_tools` 才是关键门禁。**

### 16.4 为什么采用硬规则 + LLM Judge

> LLM Judge 擅长评价相关性、完整性和表达质量，但不能可靠证明权限检查、真实工具成功或危险操作没有发生。程序化规则负责不可妥协的**安全与证据边界**，Judge 负责**主观质量**；两者职责不同，不能互相替代。

例如实时价格用例检查 `authoritative_tools_used`，而不是 `tools_used`。调用失败或 fallback 不能冒充权威证据。

### 16.5 为什么意图准确率不直接计入对话 pass rate

最终产品体验由完整回答决定，多 Agent 协作或后续工具链有时能纠正主路由。因此意图指标作为诊断信号单独报告，避免与端到端结果重复计分。

但如果某个意图直接决定隐私或交易边界，就不能只当诊断项，应把对应行为提升为硬门禁。

### 16.6 baseline 回归怎么做

系统可以和上次内存报告或保存的 baseline 比较，相对下降超过约 5% 时报告回归；只有显式 `update_baseline=true` 才更新基线。

生产化要增加：

- 数据集版本/hash；
- Prompt、模型、Embedding、工具和 Git SHA；
- 同一数据集才允许比较；
- 最小绝对差与置信区间；
- baseline 原子写、加锁和审批发布；
- 费用、耗时和工具成功率回归。

### 16.7 LLM-as-Judge 的局限

当前 Judge 仍有这些边界：

- temperature=0 不代表完全确定；
- 从文本首尾花括号解析 JSON，缺少严格 Schema、范围和 NaN 校验；
- 用户输入、历史和回答直接进入 Judge Prompt，存在评测 Prompt Injection；
- 回答模型与 Judge 若来自同一模型/供应商，会产生相关偏差；
- 默认样本量较小，没有置信区间和重复裁判；
- 单 case 异常可能中止整次 run；
- 历史列表会持续增长，不同 case 集之间比较可能失真。

建议使用独立 Judge 模型、结构化输出、分数 clamp、对抗样本、人工标定集和定期一致性校准。高风险结论始终由确定性规则判定。

### 16.8 RAG 专项评测应补什么

目前端到端框架能检查是否使用知识库，但完整 RAG 评测还应分层：

| 层次 | 指标示例 |
|---|---|
| 召回 | Recall@K、Hit Rate、MRR、nDCG |
| 重排 | Top-K relevance、pairwise win rate |
| 生成 | faithfulness、answer relevance、citation correctness |
| 系统 | P50/P95 延迟、单问 Token/费用、超时率、缓存命中率 |
| 安全 | 注入遵从率、跨租户泄露率、非权威事实率 |

必须使用带来源标注的领域数据集，并单独测试无答案问题，防止系统在检索不到证据时仍强行生成。

### 16.9 评测模块的代码级追问

- `IntentTestCase.context` 虽然存在，但当前 IntentEvaluator 没有把它传给 `recognize`，因此不能声称已覆盖上下文意图评测；
- 禁忌检测依赖固定否定窗口和词表，存在误报与漏报；
- 诊断规则默认不影响 pass，关键业务必须显式配置硬门禁；
- `/eval/run` 是高成本同步接口，即使有管理员密钥，也应该迁移到任务队列并设置并发配额；
- baseline 由普通文件写入，多 worker 或并发更新可能竞争；
- 评测管理员密钥未配置时返回 503，而不是静默放开，这属于 fail closed。

## 17. 监控、异常检测与 Prometheus 面经

### 17.1 PerformanceMonitor 的监控闭环

应用启动后，PerformanceMonitor 默认每 10 秒采样一次 Orchestrator 和 ToolManager 的累计统计：

```text
采集 Agent/Tool 成功率和平均延迟
→ 固定阈值检测
→ 窗口 Z-score 异常检测
→ 生成告警与优化建议
→ 可选发送 Webhook
→ 计算 routing_penalty
→ 回写 AgentOrchestrator 路由权重
```

默认关注的阈值包括：

- Agent 成功率低于 0.90；
- 工具成功率低于 0.95；
- Agent 平均延迟高于 3000ms；
- 工具平均延迟高于 5000ms。

异常检测使用窗口 60、阈值 2.5 的 Z-score，并要求至少 30 个点后启用。路由惩罚最高为 0.9。

### 17.2 监控如何反哺 Agent 路由

这不是只展示仪表盘：在线质量下降时，Monitor 会给对应 Agent 计算 penalty，Orchestrator 选实例时把它计入路由得分。

高频问题：自动降权最大的风险是什么？

> 短期抖动或低流量可能把健康 Agent 错误降权；流量变少后又没有新样本证明其恢复，形成“越少流量越无法恢复”的正反馈。生产方案要增加最小请求数、EWMA、惩罚衰减、少量探索流量、恢复探测和人工 override。

当前每类 Agent 只有一个实例，所以动态降权更多是扩展架构；不能描述成已经完成成熟的多副本负载均衡。

### 17.3 Gauge、Counter 和 Histogram 如何选择

- Counter：只增不减的请求数、错误数、Token 数、工具调用数；
- Gauge：当前并发、队列长度、熔断状态、最近窗口成功率；
- Histogram：每次请求完成时观察单请求延迟、Token 和费用，用于 P50/P95/P99；
- Summary：客户端计算分位数，多实例聚合困难，通常优先 Histogram。

高频问题：为什么不能每 10 秒把累计平均延迟写进 Histogram？

> Histogram 的每次 observe 应代表一个独立事件样本。重复观察累计均值会制造一组“平均值的分布”，无法还原真实尾延迟，也不能正确计算 P95/P99。

### 17.4 当前 Prometheus 实现的真实边界

面试中需要主动说明：

1. 示例配置默认 `PROMETHEUS_PORT=0`，此时自定义指标初始化不执行；FastAPI `/metrics` 通常只输出默认 Python 进程指标。
2. `requests_total` 虽已创建，但请求链没有调用 `.inc()`。
3. Agent latency Histogram 观察的是周期性累计平均值，不是单请求延迟。
4. 若设置非零端口，又会启动独立 Prometheus HTTP server，同时 FastAPI 仍暴露 `/metrics`，形成两个指标入口。
5. 统计、告警、建议和路由惩罚均在进程内存中，多 worker 之间不一致。
6. 同一阈值每轮都可能新增告警，没有去重、恢复事件和过期，可能引发 Webhook 风暴。
7. Alert 的 `resolved` 字段目前没有真正更新。
8. 示例中的部分监控开关和异常阈值配置尚未接入代码。

因此当前更准确的表述是“已有监控闭环原型”，而不是“已经建立完整生产级可观测平台”。

### 17.5 生产指标应该在哪里记录

请求级指标应在真实事件发生处记录：

- HTTP middleware：请求数、状态码、端到端延迟、在途请求；
- Agent 完成点：Agent 类型、成功/失败、单次耗时；
- ToolManager：工具调用、缓存、fallback、熔断拒绝、单次耗时；
- LLM Client：模型、Token、首 Token 延迟、总延迟、错误类型、费用；
- RAG：rewrite 数、召回耗时、候选数、Top-K、rerank 耗时；
- Memory：读写、压缩、CAS 重试、长期存储失败。

标签必须控制基数。不要把 user_id、conv_id、完整异常、query 或 order_id 当作 Prometheus label。

### 17.6 建议的 SLI/SLO

| 目标 | SLI 示例 | SLO 示例 |
|---|---|---|
| 可用性 | 非预期 5xx 比例 | 月度 99.9% |
| 延迟 | `/chat` P95/P99 | P95 < 5s |
| 证据可靠性 | required tool 权威成功率 | > 99% |
| RAG 质量 | 线上抽样 faithfulness | > 0.9 |
| 隐私 | 跨主体数据泄露事件 | 0 |
| 成本 | 每成功回答平均费用 | 按业务预算 |

具体阈值应从真实负载和用户期望倒推，不能照搬示例值。

### 17.7 多实例监控怎么做

> 每个 Pod 暴露原始 Counter/Histogram，由 Prometheus 按标签聚合。告警去重、静默、升级和恢复交给 Alertmanager。若路由健康状态需要跨实例共享，应进入统一控制面或服务发现系统，不能依赖某个 Uvicorn 进程的内存字典。

## 18. Docker、Nginx 与生产部署面经

### 18.1 当前部署拓扑

```mermaid
flowchart LR
    USER["客户端"] --> NGINX["Nginx :80"]
    NGINX --> API["FastAPI :8000"]
    HOST["本机 MCP Host"] --> MCP["MCP streamable-http :8010"]
    PROM["Prometheus"] --> METRICS["FastAPI /metrics"]
    API --> EXT["外部 Redis / Milvus / PostgreSQL / Java / LLM"]
    MCP --> JAVA["Java ModelHub"]
```

Compose 将 FastAPI、标准 MCP、Prometheus 和 Nginx 分开部署；Redis、Milvus、PostgreSQL 被视为外部基础设施。

### 18.2 当前容器化亮点

- Dockerfile 使用多阶段构建；
- 运行镜像使用 UID 1000 非 root 用户；
- 清理 apt/pip 缓存并配置健康检查；
- `.dockerignore` 排除 `.env`、Git、虚拟环境、缓存和日志；
- MCP 端口只绑定 `127.0.0.1:8010`，默认不直接对公网开放；
- Nginx 配置请求速率、并发、gzip、安全响应头和 upstream keepalive；
- Prometheus 使用持久卷并设置保留时间。

这些是良好的基础，但仍不能直接等同于生产就绪。

### 18.3 为什么直接暴露 8000 是严重问题

Compose 同时发布 FastAPI 的 `8000:8000` 和 Nginx 的 `80:80`。客户端可以绕过 Nginx，直接访问应用端口，从而绕过 Nginx 限流、指标 ACL 和未来配置的网关鉴权。

正确做法：

- FastAPI 只使用 Compose `expose`，不发布宿主端口；或仅绑定回环地址；
- 外网只暴露负载均衡器/Nginx 的 443；
- 网络安全组也要禁止直连应用端口；
- 管理接口和业务接口分离网络或路由。

### 18.4 TLS 和 Bearer Token

当前 Nginx TLS 配置处于注释状态。如果没有上游 LB 终止 TLS，Bearer Token 会通过明文 HTTP 传输。生产必须明确 TLS 终止点、证书轮换、HTTP 到 HTTPS 跳转以及可信代理头配置。

只有在整条外部链路均为 HTTPS，并正确处理反向代理时，才适合启用 HSTS。不要在本地 HTTP 环境盲目开启。

### 18.5 镜像与容器加固

当前还应增加：

- 镜像版本或 digest 固定，避免 `latest` 漂移；
- SBOM、依赖漏洞扫描、镜像签名和来源验证；
- `read_only` root filesystem，仅挂载必要写目录；
- `cap_drop: [ALL]`、`no-new-privileges`；
- CPU、内存、PID 和临时空间限制；
- 容器日志轮转；
- 独立服务账号与最小环境变量；
- 备份恢复演练和数据库迁移流程。

`container_name` 会妨碍 Compose 水平扩容，单节点 upstream 下 `least_conn` 也没有实际负载均衡价值。

### 18.6 Secret 管理

当前仓库的 `.env` 已被 Git 跟踪；后来加入 `.gitignore` 并不会删除 Git 历史中的内容。正确处置顺序是：

1. 立即轮换可能出现过的所有凭据；
2. 从 Git index 移除 `.env`；
3. 根据组织策略清理历史并通知所有协作者重新同步；
4. 启用 secret scanning 和 pre-commit 检测；
5. 运行时改用 Vault/KMS/Kubernetes Secret/Docker Secret；
6. MCP、API、Evaluator 各自只获得所需最小密钥。

部署脚本还会明文备份 `.env`，健康检查可能打印完整 `REDIS_URL`。如果 URL 含密码，会进入终端或 CI 日志。敏感值只能打印脱敏版本，备份必须加密并限制权限。

### 18.7 配置和脚本中的追问陷阱

- Prometheus 的指标 ACL 硬编码了子网，但 Compose 网络没有固定对应网段；
- Prometheus 引用了告警规则目录，Compose 没有挂载规则，也没有 Alertmanager；
- Nginx 的静态目录没有挂载进容器；
- 构建测试脚本指向不存在的 Dockerfile test stage；
- 默认构建可能落到最后的 development stage，而不是预期生产 stage；
- 运行脚本映射 9090，但默认 Prometheus 端口为 0，通常没有服务监听；
- 部署脚本使用 `eval` 执行拼接命令，CLI 参数可能造成 shell 注入；
- App 与 MCP 共用完整 `.env`，违反最小权限。

面试中把这些说成“我在上线审查中发现并规划修复的部署风险”，比假装配置已经完美更有可信度。

### 18.8 生产化推荐拓扑

```text
Internet
→ WAF / LB / Nginx 443
→ 无状态 FastAPI Pods
   ├─ Redis Cluster：短期会话、幂等键
   ├─ Milvus：知识与长期记忆
   ├─ PostgreSQL：审计、任务、outbox
   ├─ Java ModelHub：业务事实与资源级授权
   └─ LLM Gateway：模型与 Embedding

独立管理面
→ RBAC 管理 API
→ 知识导入 Worker / Eval Worker

可观测面
→ OpenTelemetry Collector
→ Prometheus + Grafana + Alertmanager
→ 日志与 Trace 后端
```

API Pod 保持无状态；评测和知识导入使用独立异步 Worker；`/livez` 只检查进程，`/readyz` 用短超时检查关键依赖；MCP 远程服务放在受控网关后并单独鉴权。

## 19. 安全模型与 Prompt Injection 面经

### 19.1 系统中的四类信任等级

| 等级 | 示例 | 处理原则 |
|---|---|---|
| 受信任代码/配置 | ToolPolicy、Agent 映射、服务端 locked inputs | 可以决定授权边界 |
| 受信任仓库内容 | 审核后的 `SKILL.md` | 可注入 system，但必须走发布审查 |
| 外部数据 | RAG 文档、Java 返回字段、工具结果 | 只当数据，不可提升为指令 |
| 用户输入 | message、上传内容、匿名标识 | 默认不可信，校验、限额、隔离 |

安全核心不是“让模型更听话”，而是确保低信任数据无法改变高信任授权。

### 19.2 Prompt Injection 的主要入口

- 用户消息直接要求忽略 system 规则；
- RAG 文档包含伪造指令；
- 模型/套餐名称或错误信息中嵌入提示；
- 用户上传文档在入库后成为持久化攻击载荷；
- Skill 仓库或依赖供应链被篡改；
- Judge Prompt 被待评测文本操纵。

### 19.3 当前已经实现的防线

- Skill 放在 system 层，用户消息不能直接覆盖；
- 模型只看到 Agent 的最小工具白名单；
- locked inputs 覆盖模型提交的关键 ID；
- 私有工具完全不注册给模型；
- 工具结果被声明为不可信数据；
- required tool 只有成功且 authoritative 才算完成；
- RAG 仅拼接权威检索结果；
- 私有载荷做字段投影、长度和数量限制；
- 响应模型不回传认证 context 和原始工具载荷。

### 19.4 为什么 Prompt 规则不等于安全沙箱

> System Prompt 只能降低模型服从恶意数据的概率，不能提供形式化隔离。真正的安全控制必须落在代码：工具不注册、权限最小化、服务端锁参、资源级授权、无写操作、输出过滤和审计。

对于未来写工具，需要额外增加：

1. plan 与 execute 分离；
2. 展示规范化操作摘要；
3. 用户显式确认；
4. 短时一次性 capability token；
5. 幂等键和补偿动作；
6. 高风险操作双人审批；
7. 不可抵赖审计。

### 19.5 威胁建模高频问题

Q：只要工具是只读的，就绝对安全吗？

> 不是。只读工具仍可能泄露隐私、造成后端 DoS、跨租户缓存污染，或把恶意数据带入 Prompt。仍要鉴权、资源归属校验、限流、缓存隔离、字段最小化和结果大小限制。

Q：为什么 Tool annotations 不是权限控制？

> MCP 的 read-only、idempotent 等 annotations 是供 Host 和模型理解的语义提示。恶意客户端不必遵守；服务端必须通过实际注册范围、认证、授权和后端实现保证边界。

Q：如何防止越权查询订单？

> Python 层不向模型暴露私有工具，并根据显式动作预取；Token 不由模型提供；响应字段最小化。但最终决定性控制是 Java 后端以认证主体校验 order_id 归属。需要负向集成测试证明 A 用户不能读取 B 用户订单。

### 19.6 当前安全修复优先级

| 优先级 | 工作 |
|---|---|
| P0 | 轮换已暴露风险的 Secret；保护知识写入/reset、monitor、tool debug；禁止直连 8000；确认 Java 资源归属授权 |
| P1 | 精确 CORS、稳定主体 ID、请求幂等与全链路 deadline、管理 RBAC、上传限额与异步导入 |
| P2 | MCP HTTP 鉴权/TLS/限流、结构化工具输出、Skill 供应链校验、审计 outbox |
| P3 | 写工具确认协议、集中策略引擎、自动红队与持续安全评测 |

## 20. 配置、依赖与启动治理面经

### 20.1 当前配置如何加载

`api/main.py` 在导入阶段调用 `load_dotenv()`，随后通过多个函数读取环境变量：

- `_anthropic_cfg`：API Key、模型和 Base URL；
- `_storage_cfg`：Milvus、Embedding、PostgreSQL；
- `_model_hub_cfg`：Java 后端开关、地址和超时；
- `_agent_tool_cfg`：工具轮次、总调用数、并发和结果长度。

`ANTHROPIC_API_KEY` 缺失时启动失败；相对 Skill 路径会固定解析到项目根目录，避免 Uvicorn 或 IDE 工作目录不同导致找不到文件。

Windows 后台启动时还要保证 Python 标准输出使用 UTF-8。项目启动横幅包含 Unicode 字符，若隐藏进程继承 GBK 控制台编码，可能在应用监听端口前触发 `UnicodeEncodeError`。可设置 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`，或把启动日志改为不依赖特殊字符。

### 20.2 配置为什么要强类型校验

当前通过 `int()`、`float()` 和字符串比较解析配置，非法值会在启动时抛异常。启动失败比运行中使用错误配置更安全，但错误信息、范围检查和跨字段检查仍不够统一。

生产中可以使用 Pydantic Settings：

- 类型、范围、枚举和必填项一次定义；
- 把 Secret 类型与普通字符串区分；
- 校验 Base URL 协议/Host；
- 校验 `tool_max_parallel_calls <= tool_max_calls`；
- 校验 Embedding 输出维度与 Milvus collection 一致；
- 输出脱敏后的有效配置摘要；
- 未接线的环境变量在 CI 中被检测出来。

配置示例不等于配置已经生效。当前 Swagger、监控开关和部分异常阈值的示例变量尚未全部接入代码，面试时不能把它们当成已实现特性。

### 20.3 Embedding 配置漂移为什么危险

如果已经用某个模型和维度写入 Milvus，后来只修改环境变量再启动，查询向量可能与历史向量语义空间不同，即使维度相同也会静默失真。

应记录并校验：

- embedding backend、模型名和版本；
- 维度、query/document instruction；
- 归一化方式；
- chunker 版本；
- corpus version。

模型变更时创建新 collection 或版本化 alias，离线重建并验证后再原子切流，不能直接混写。

### 20.4 依赖治理

`requirements.txt` 同时使用精确版本和范围版本。精确版本提高复现性，范围版本便于兼容升级，但只靠 requirements 仍缺少完整传递依赖锁。

生产建议：

- 使用 lock 文件记录完整依赖树与哈希；
- 定期自动升级，但通过单测、端到端评测和镜像扫描门禁；
- 为 PyTorch/sentence-transformers 区分 CPU/GPU 镜像；
- 固定 MCP、Anthropic SDK 与协议兼容测试；
- 生成 SBOM，并对高危 CVE 建立修复时限。

## 21. 测试体系面经

### 21.1 当前 58 项离线测试覆盖

| 测试文件 | 测试数 | 主要覆盖 |
|---|---:|---|
| `test_agent_tool_loop.py` | 14 | 工具轮次、预算、并发顺序、重复调用、越权、强制工具、失败关闭、错误降级 |
| `test_api_auth_and_tools.py` | 9 | Bearer 边界、身份哈希、数值型用户 ID 归一化、私有字段投影、私有触发、评测鉴权 |
| `test_evaluator_rules.py` | 10 | 禁忌否定语境、软/硬门禁、多轮隔离、baseline opt-in |
| `test_memory_concurrency.py` | 4 | Redis CAS 压缩竞态、键编码、评测审计隔离 |
| `test_model_hub_units.py` | 3 | 分/元单位、嵌套响应、实时取价成本 |
| `test_modelhub_mcp.py` | 4 | 公共工具、确定性成本、MCP stdio 协议往返 |
| `test_orchestrator_metadata.py` | 1 | 并行主 Agent 与元数据 |
| `test_project_skills.py` | 7 | Skill 加载/路由、私有工具隐藏、请求克隆、失败关闭 |
| `test_tool_manager_security.py` | 6 | 缓存隔离、fallback、业务失败、参数校验、取消、半开探针 |

### 21.2 测试亮点怎么讲

> 测试重点不是只有 happy path，而是验证系统边界：429 不能绕过 required tool、fallback 不能变成权威证据、同轮并发仍保持 tool_result 顺序、Redis 压缩期间新增消息不能丢、MCP 要通过真实 stdio 协议往返而不是只调用 Python 函数。

这种测试比“接口返回 200”更能体现 Agent 工程质量。

### 21.3 单元测试、集成测试、评测如何分工

| 层级 | 验证对象 | 特点 |
|---|---|---|
| 单元测试 | Policy、Schema、路由、CAS 算法、成本纯函数 | 快、确定、适合每次提交 |
| 组件/协议测试 | MCP stdio、HTTP mock、Redis/Milvus adapter | 验证协议与边界 |
| 集成测试 | FastAPI lifespan + Java/Redis/Milvus/Postgres | 验证真实装配和兼容性 |
| 端到端评测 | 完整对话质量、安全门禁、回归 | 较慢、可能包含模型不确定性 |
| 负载/故障测试 | 并发、尾延迟、连接池、依赖故障 | 上线前与定期执行 |

### 21.4 当前测试缺口

- 没有使用 ASGI lifespan 的真实路由集成测试；
- 没有从 HTTP Header 到 Java mock、Memory、Agent 和 ChatResponse 的完整 `/chat` 测试；
- 没有验证 ModelHubClient 的 Authorization 前缀、非 JSON、超时、响应过大和 5xx；
- 没有 PerformanceMonitor 指标语义、告警去重和惩罚恢复测试；
- 没有 Docker Compose/Nginx 配置静态验证；
- 没有知识管理鉴权、上传大小和事件循环阻塞测试；
- 没有 Judge 异常值、评测注入、baseline 并发和单 case 隔离测试；
- 没有真实 Java、Redis、Milvus、PostgreSQL、Nginx、Docker 联调；
- 没有负载测试、长稳测试和故障注入；
- 没有 property-based/fuzz 测试工具 Schema 与私有字段投影。

### 21.5 建议的 CI 门禁

```text
静态检查 / Secret scan / 依赖扫描
→ 单元测试
→ MCP 协议测试与 ASGI 集成测试
→ 临时 Redis/Milvus/PostgreSQL/Java stub 集成环境
→ 固定数据集的 Agent/RAG 评测
→ 指标达到阈值且没有安全硬规则失败
→ 构建并扫描镜像
→ staging 冒烟与回滚演练
```

模型评测应保存成本和版本；普通代码 PR 跑小数据集，Prompt/模型/Embedding/Tool 变更跑完整数据集。

## 22. 故障处理与可靠性面经

### 22.1 依赖故障矩阵

| 故障 | 当前主要表现 | 正确的面试结论 |
|---|---|---|
| LLM 网关 429/5xx | 意图链可用 Embedding/Pattern 降级，但最终 Agent 生成仍可能失败 | 不能把网关错误伪装成“不支持 tools”；需要分类错误、限流和全链路预算 |
| Java 业务 API 失败 | ToolManager 记失败、可熔断；可选工具可返回非权威 fallback | required evidence 必须 fail closed，不能猜实时价格/状态 |
| Milvus 启动不可达 | KnowledgeBase/向量存储初始化可能使应用启动失败 | 若 RAG 是硬依赖就 readiness 失败；若允许降级则延迟初始化并明确能力状态 |
| Milvus 运行期检索失败 | 知识工具可 fallback；情景记忆检索捕获异常后返回空 | fallback 只保可用性，不代表权威知识 |
| Redis 运行期不可达 | 主链读取工作记忆没有统一降级，可能使 `/chat` 失败 | 需明确 Redis 是硬依赖还是允许无记忆模式，并加入 deadline/错误映射 |
| PostgreSQL 不可达 | 审计层 best-effort，记录 warning 后聊天继续 | availability-first；强合规场景需 WAL/outbox 和硬审计门禁 |
| 画像后台任务失败 | 不阻塞主响应，但任务未集中回收 | 建立任务集合/队列、重试、DLQ 和关闭等待 |
| Monitor/Webhook 失败 | 应与聊天主链隔离 | 监控不能反向拖垮业务，但必须监控“监控自身” |
| 标准 MCP 后端失败 | Tool 可能返回 `success:false` 的业务结果 | MCP 客户端必须检查业务字段，协议成功不等于业务成功 |

### 22.2 为什么 required tool 失败要 fail closed

如果问题是“当前模型价格多少”“我的订单是什么状态”，答案的正确性依赖实时权威证据。此时继续生成一个听起来合理的答案，会把可用性问题变成数据真实性问题。

> fail closed 不是让整个服务粗暴报错，而是给出**安全、可行动的响应**：说明当前无法核验、不要做事实断言、提供重试或人工渠道，并保留工具失败审计。

### 22.3 熔断、重试、限流、超时分别解决什么

| 机制 | 解决的问题 | 常见错误 |
|---|---|---|
| 超时 | 单次调用无限等待 | 每层独立超时相加超过总 deadline |
| 重试 | 短暂网络/服务抖动 | 非幂等重试、无退避、形成重试风暴 |
| 熔断 | 持续故障时快速失败并保护依赖 | 全局熔断被非法参数触发、没有半开探测 |
| 限流 | 控制入口流量和公平性 | 只在 Nginx 限流却允许绕过网关 |
| Bulkhead | 隔离不同工具/租户资源 | 一个慢工具占满所有并发槽 |
| fallback | 提供降级信息或旧数据 | 把降级结果标为权威实时事实 |

这些机制相互补充，不是同义词。

### 22.4 全链路 deadline 如何设计

假设 `/chat` 总预算 8 秒：

1. API 入口记录绝对 deadline；
2. Memory 读取使用较短预算；
3. Intent、Embedding 并行并共享剩余时间；
4. ToolLoop 每轮根据剩余时间决定是否还能调用；
5. 下游 HTTP timeout 不得超过剩余预算；
6. 保留最后少量时间生成安全终结响应；
7. deadline 传入日志、Trace 与工具记录。

仅配置“每个工具 5 秒”并不够；3 轮串行调用可能远超用户可接受时间。

### 22.5 一致性与 exactly-once

当前系统包含 Redis、Milvus、PostgreSQL 三种存储，不可能靠一个本地事务实现跨库强一致：

- Redis CAS 保证工作记忆与摘要的原子更新；
- Milvus 情景记忆在 CAS 成功后写入，崩溃窗口仍可能漏写；
- PostgreSQL 审计失败不会回滚 Redis；
- 画像后台更新可能晚到或乱序。

生产上采用“本地原子事件 + 幂等消费者”的最终一致性：Redis Stream 或 PostgreSQL outbox 记录带事件 ID、主体、版本和 payload hash 的事件，由消费者写 Milvus，并支持重试、去重和死信。

### 22.6 缓存一致性

ToolManager 的 TTL 缓存适合公共只读数据，但仍要回答三个问题：

1. **谁拥有真相？** Java 服务或知识 corpus；
2. **允许多旧？** 不同工具按业务设置 TTL；
3. **如何主动失效？** 价格/套餐变更事件、知识 corpus version、管理 reset 后清缓存。

私有工具默认不缓存；若未来缓存，必须把稳定租户主体纳入 key，并确保上下文原文不出现在 key 和日志中。

## 23. 系统设计深挖题

### 23.1 如果流量增长到 1 万 QPS，先改什么

参考回答：

1. FastAPI 无状态化并水平扩容，去掉进程内共享正确性依赖；
2. 复用 LLM/Java HTTP 连接池，异步 Redis/PostgreSQL/Milvus 客户端；
3. API Gateway 做认证、租户级限流、请求大小限制和配额；
4. 意图识别采用小模型/分类器并缓存，减少每问两次 LLM；
5. 公共目录和知识检索做多级缓存与 singleflight；
6. ToolManager 按依赖设置 bulkhead、全局 deadline 和熔断；
7. 画像、审计、知识导入、评测进入异步队列；
8. Prompt/工具结果严格预算，热点问题可预计算；
9. Prometheus 聚合原始指标，OpenTelemetry 串起跨服务 Trace；
10. 用压测结果定位瓶颈，而不是只增加 worker。

LLM 网关通常先成为成本和吞吐瓶颈，因此要同时做模型路由、批处理、语义缓存和租户预算治理。

### 23.2 当前请求为什么可能很慢

一条复杂请求可能包含：

```text
记忆检索
→ 意图 LLM 与 Embedding
→ 第二次 LLM 实体提取
→ Agent 首轮 LLM
→ 工具 HTTP / RAG
→ RAG query rewrite LLM
→ 多路向量召回
→ rerank LLM
→ Agent 终结 LLM
```

其中多段是串行关键路径。优化顺序：

- 合并意图和实体结构化输出；
- 对无需工具的简单问题走小模型快速路径；
- 只有检索质量不足时才 rewrite/rerank；
- 同轮独立工具并发；
- 连接池、超时和缓存；
- 记录每个 span 的耗时与 Token，再针对真实瓶颈优化；
- 允许流式输出，但不能在权威证据返回前流出未经核验的事实。

### 23.3 如何做多租户隔离

需要同时覆盖：

- 认证：稳定 principal 和 tenant；
- 授权：Java 后端资源归属、管理 RBAC；
- 存储：Redis key、Milvus filter、Postgres tenant key/RLS；
- 缓存：tenant-aware key 或私有工具禁用缓存；
- 限流/预算：按 tenant/user/API key；
- 观测：可按 tenant 聚合但避免高基数和 PII；
- 数据生命周期：TTL、导出、删除和审计；
- 模型上下文：任何跨租户数据都不能进入同一 Prompt。

只在 Prompt 中写“不要泄露其他用户数据”不算租户隔离。

### 23.4 如何让 RAG 支持知识更新和回滚

推荐版本化发布：

```text
原始文档进入对象存储
→ 清洗/切片/Embedding 生成 corpus_vN
→ 离线召回与生成评测
→ 人工审批
→ Milvus alias 原子切到 vN
→ 清理查询缓存
→ 保留 vN-1 便于回滚
```

文档 ID 应包含稳定 source_id、版本和 chunk 位置；更新时删除旧版本或基于 alias 切换，避免不同版本重复召回。

### 23.5 如果要增加写操作 Agent，架构怎么变

不能简单把 POST API 注册成工具。应引入状态机：

```text
DRAFT 生成计划
→ VALIDATED 服务端校验权限和参数
→ AWAITING_CONFIRMATION 用户查看不可歧义摘要
→ AUTHORIZED 签发一次性 capability
→ EXECUTING 使用幂等键执行
→ SUCCEEDED / FAILED / COMPENSATING
```

金额、对象、时效和不可逆影响要在确认界面明确展示。高风险操作不能依赖模型转述作为用户确认。

### 23.6 为什么需要集中策略引擎

当前 ToolPolicy 在 Orchestrator 中按 Agent 生成，规则清晰但逐渐增多后容易分散。生产可以把“主体、意图、工具、资源、风险级别、环境”输入策略引擎，输出 allow/deny、参数约束、确认方式和审计级别。

LLM 只提供语义信号，策略引擎做最终授权。策略要版本化、可测试、可解释，并支持紧急禁用某个工具。

## 24. 高频面试题速答

### 24.1 Agent、MCP 与 Skills

| 问题 | 建议速答 |
|---|---|
| Agent 和普通 Workflow 的区别？ | Workflow 的步骤由代码预先确定；Agent 允许模型在状态和工具约束内动态选择下一步。本项目是“**确定性编排 + 局部 Agent 自治**”的混合方案。 |
| 为什么要让 LLM 参与工具决策？ | 用户表达不固定，模型能判断何时需要外部事实和哪个公共工具最相关；但授权、关键参数、预算和权威判定仍由代码控制。 |
| Function Calling 和 MCP 的区别？ | Function Calling 是**模型 API 的工具调用协议**；MCP 是 **Host 与外部能力服务之间的发现/调用协议**。本项目 AgentToolLoop 使用前者，`modelhub_mcp` 实现后者。 |
| MCPToolManager 是 MCP Server 吗？ | 不是，它是进程内工具治理框架；标准 MCP Server 位于 `modelhub_mcp`。 |
| Skill 会自动执行工具吗？ | 不会。Skill 是**受信工作流指令**，ToolPolicy/AgentToolLoop 才负责工具选择与执行。 |
| 为什么不把所有 Skills 一次注入？ | 会增加 Token、冲突和攻击面；按 Agent 确定性加载更易审计。 |
| 多 Agent 为什么不完全交给模型组织？ | Agent 划分同时是**业务和权限边界**，代码路由更可重复；模型负责语义信号与局部决策。 |
| 什么情况下不要使用 Agent？ | **流程固定、低延迟、严格事务或高风险写操作**时，确定性代码/状态机通常更合适。 |

### 24.2 RAG、Embedding 与 Memory

| 问题 | 建议速答 |
|---|---|
| RAG 和微调如何选择？ | RAG 适合**频繁变化、需要来源**的知识；微调更适合**稳定行为和输出风格**。二者可组合，实时价格必须走权威 API 而不是只靠 RAG。 |
| 为什么用向量库？ | 解决语义近似检索和大规模 Top-K；但向量相似度不是最终相关性，所以还要去重和 rerank。 |
| chunk 为什么约 500 字？ | 在**语义完整性、召回粒度和 Prompt 成本**间取折中；真实最优值应由数据集评测，不是固定真理。 |
| 为什么需要 overlap？ | 当前实现没有 overlap，跨 chunk 信息可能丢失；重叠或语义/结构化切片能改善边界召回，但会增加存储和重复结果。 |
| query rewrite 与 rerank 分别解决什么？ | rewrite 提高召回率，解决“找不全”；rerank 提高 Top-K 精度，解决“排不好”。 |
| stable hash embedding 能做什么？ | 它是确定性字符 n-gram 哈希兜底，零模型依赖，但不是真正深层语义向量。 |
| 为什么 RAG 与 Memory 分开？ | RAG 面向共享知识事实，Memory 面向用户和会话状态；生命周期、权限、写入来源和检索条件不同。 |
| Redis 和 PostgreSQL 为什么并存？ | Redis 负责低延迟 TTL 工作记忆与 CAS；PostgreSQL 负责可查询、持久的可选审计。 |
| 为什么 CAS 比进程锁可靠？ | WATCH/MULTI 在数据所在的 Redis 上控制并发，可跨进程；`asyncio.Lock` 只能保护单进程协程。 |
| 如何评测 RAG？ | 拆成 Recall@K/MRR/nDCG、重排质量、faithfulness/citation、延迟/成本和注入安全。 |

### 24.3 工程、安全与评测

| 问题 | 建议速答 |
|---|---|
| tools_used 为什么不够？ | 它只能证明尝试过；实时结论必须由成功、非 fallback、authoritative 的记录支持。 |
| fallback 和 retry 的区别？ | retry 是再次尝试原调用；fallback 是返回替代能力或降级信息。当前项目没有通用 retry。 |
| 熔断为什么要 HALF_OPEN？ | 恢复窗口只放一个探针，成功关闭、失败重开，避免刚恢复就被流量压垮。 |
| 如何防止模型越权改参数？ | 模型输入先合并 defaults，再由服务端 locked_inputs 最终覆盖并做 Schema 校验。 |
| 如何防止无限工具循环？ | 限制轮次、总调用数、单轮并发，并用工具名加规范化参数哈希去重。 |
| 为什么私有查询不开放给模型？ | 意图判断不能代替认证和资源授权；私有工具由 API 代码确定性调用，最终由 Java 校验资源归属。 |
| 为什么不能只靠 LLM Judge？ | Judge 适合主观质量，权限、危险动作和权威证据必须由程序化硬规则判断。 |
| 如何降低 Agent 成本？ | 小模型路由、合并意图/实体、按需 rewrite/rerank、缓存、结果预算、并行工具和逐请求成本指标。 |
| 如何定位慢请求？ | 用 Trace 拆分 Memory、Intent、每轮 LLM、Tool、向量召回、rerank 和持久化 span，再看 P95/P99。 |
| 项目上线前最先修什么？ | Secret 轮换、管理接口鉴权、禁止绕过 Nginx、资源级授权验证、真实指标和 ASGI/外部依赖集成测试。 |

## 25. 面试中必须诚实说明的实现边界

| 主题 | 不能夸大的说法 | 准确说法 |
|---|---|---|
| Multi-Agent | “已经做了成熟多实例调度” | 当前每类一个实例，已有池化评分和并行协作框架 |
| 答案综合 | “多个 Agent 会自动解决冲突” | 当前主要按标签拼接文本，尚无结构化 Synthesizer |
| 人工审核 | “有完整人工工单系统” | 有 MANUAL_REVIEW 类型/Skill/标记，但无独立审核池和工单适配器 |
| 意图置信度 | “返回的是三路融合置信度” | 最终意图来自加权投票，但返回 confidence 当前仍偏向 LLM 原始值 |
| 意图缓存 | “完整上下文缓存” | key 主要取消息前 200 字，未纳入历史，存在上下文串用风险 |
| Schema | “完整 JSON Schema 验证” | 当前主要是浅层类型、必填、范围和额外字段检查 |
| 内部 MCP | “主 Agent 直接通过标准 MCP 网络调用” | 主链使用进程内 ToolManager；独立标准 MCP 服务供外部 Host 使用 |
| 标准 MCP 安全 | “可安全直接公网开放” | 目前只开放公共只读工具；HTTP 传输仍需网关鉴权、TLS、限流 |
| Embedding | “默认就是强中文语义模型” | 默认 stable hash 是字符 n-gram 兜底；可配置 sentence-transformers |
| RAG | “实现了混合检索和引用闭环” | 当前是向量召回 + rewrite + LLM rerank，没有 BM25、分数阈值和完整 citation |
| Chunking | “已处理所有长文本边界” | 按标点约 500 字、无 overlap，超长单句仍可能形成大 chunk |
| Memory | “跨 Redis/Milvus/Postgres exactly-once” | Redis 内 CAS；跨存储只有 best-effort，需 outbox/stream |
| 监控 | “Prometheus 指标已生产可用” | 已有监控闭环原型，但默认自定义指标未注册且 Histogram 语义需修复 |
| 部署 | “容器配置已生产就绪” | 有非 root、多阶段、Nginx/Prometheus 基础，但仍存在端口绕过、TLS/Secret/镜像治理缺口 |
| 测试 | “完成真实全链路联调” | 58 项离线测试已覆盖关键边界；尚未完成真实 Redis/Milvus/Postgres/Docker 全链路联调和压测；Java 网关与百炼已完成单请求验证 |

如果面试官指出这些问题，推荐回答结构：

> 这个判断是对的。当前实现的边界是 A，已经解决了 B 风险，但 C 尚未覆盖。若生产化，我会先用 D 验证，再通过 E 改造，并用 F 指标证明效果。

这比先争辩或含糊承认更能体现工程判断。

## 26. STAR 项目回答模板

### 26.1 “你在项目中解决过最复杂的问题是什么”

**Situation**

> 项目原先的第二条 Agent 链只把 Skill 工作流注入 system prompt。模型知道“应该查价格、套餐或知识库”，但没有真正的 tool-use 循环，最后仍可能依赖模型记忆回答实时问题。

**Task**

> 我的目标是让模型参与“是否用工具、用哪个公共工具”的语义决策，同时确保它不能扩大权限、篡改关键参数、无限调用，或把失败/fallback 当成实时证据。

**Action**

> 我先把 Agent、Skill 和 Tool 三层职责拆开：Orchestrator 根据意图选择 Agent 和 Skill，再生成最小 ToolPolicy；AgentToolLoop 实现 Anthropic 兼容的多轮 `tool_use/tool_result` 协议，加入白名单、Schema、locked inputs、去重、调用预算、并发控制和结果截断；ToolManager 统一处理缓存、超时、三态熔断、fallback 和 authoritative 标记。对于订单和账户，我没有开放给模型，而是由 API 根据明确动作和 Bearer 身份确定性预取。随后又提供独立标准 MCP，仅暴露 7 个公共只读工具，并补充协议、安全、并发与 Redis CAS 测试。

**Result**

> 第二条链从“只有工作流提示”升级为“模型在代码边界内真实调用工具”。实时事实必须有 authoritative 记录，强制工具失败会安全关闭；标准 MCP 可被外部 Host 发现和调用。当前离线测试共 58 项并已通过最近一次仓库验证，同时我明确保留了完整外部依赖联调、管理鉴权和 Prometheus 指标修复等上线任务。

### 26.2 “你遇到过什么并发问题”

> 长会话压缩先读取 Redis，再等待 LLM 生成摘要。如果期间有新消息 LPUSH，旧实现的 DEL + 重写会丢消息。我改成先在事务外生成摘要，再 WATCH 工作列表和摘要 key，确认当前列表仍以原快照为完整后缀；MULTI 中原子 LTRIM 和 SETEX，冲突就重试或放弃。只有 CAS 成功后才写 Milvus。这解决了 Redis 内丢消息，但我不会把它说成跨 Redis/Milvus exactly-once；生产上还需要 Stream/outbox 和幂等消费者。

### 26.3 “你如何平衡 Agent 自治和安全”

> 我把系统分成概率域和确定性域。LLM 可以判断公共只读工具的使用时机，但工具集合、认证上下文、关键参数、预算、资源授权、权威证据和高风险动作由代码控制。权限不是 Prompt，而是 capability。这个原则也贯穿 RAG、MCP、私有订单查询和评测硬门禁。

## 27. 简历表达参考

可以按真实参与程度选择，禁止加入未经测量的性能数字：

- 设计多 Agent 编排与受控 LLM tool-use 链路，通过 ToolPolicy、服务端锁参、调用预算、并发去重和 authoritative evidence，实现公共工具自治与私有数据确定性授权分离。
- 构建 Milvus RAG 查询改写、多路召回、内容去重和 LLM 重排链，并设计 Redis 工作记忆、摘要、Milvus 情景记忆/画像及 PostgreSQL best-effort 审计。
- 使用 Redis WATCH/MULTI/EXEC 修复长会话摘要期间的并发丢消息问题，明确跨存储一致性边界并规划 outbox 幂等落库。
- 实现标准 MCP stdio/Streamable HTTP 服务，对外提供 7 个公共只读工具，同时隔离订单和账户私有能力。
- 建立 Agent 安全与质量测试体系，覆盖强制工具失败关闭、fallback 权威性、并发顺序、缓存隔离、数值型用户 ID 兼容、MCP 协议往返和评测硬门禁，共 58 项离线测试。
- 完成 FastAPI、Nginx、Prometheus 和 Docker 部署审查，识别管理接口鉴权、直连端口、Secret 治理和指标语义等生产化风险。

不建议写：

- “RAG 准确率提升 30%”——当前没有对应基准数据；
- “支持万级 QPS”——当前没有压测；
- “实现金融级 exactly-once”——跨存储仍是 best-effort；
- “生产环境零故障运行”——没有可核验运行数据；
- “全自动人工审核”——审核工单系统尚未实现。

## 28. 五分钟白板讲解顺序

如果面试官让你现场画架构，按这个顺序：

1. 先画 `/chat` 和 FastAPI；
2. 左侧画 Memory：Redis、Milvus、PostgreSQL；
3. 中间画 IntentRecognizer → AgentOrchestrator → 专属 Agent；
4. Agent 下方画 Skill + ToolPolicy + AgentToolLoop；
5. ToolLoop 连接 ToolManager、KnowledgeBase 和 Java API；
6. 单独画外部 MCP Host → 标准 MCP Server；
7. 最后用红线标出私有工具由 API 预取，不进入模型白名单；
8. 边上补 Evaluation、Monitor、Prometheus、Nginx。

讲解时始终围绕三条线：

- **数据线**：事实从哪里来；
- **决策线**：哪些交给模型，哪些由代码决定；
- **证据线**：如何证明结果权威、隔离且可评测。

## 29. 源码复习索引

| 想复习的主题 | 建议阅读 |
|---|---|
| FastAPI 装配与主聊天链 | [api/main.py](../api/main.py) |
| Agent、路由与并行协作 | [agents/agent_orchestrator.py](../agents/agent_orchestrator.py) |
| 模型工具循环和 ToolPolicy | [agents/tool_use.py](../agents/tool_use.py) |
| 意图融合与实体抽取 | [core/intent_recognizer.py](../core/intent_recognizer.py) |
| 项目 Skills 加载 | [core/project_skills.py](../core/project_skills.py) |
| 内部工具治理、RAG rewrite/rerank | [modelhub_tools/tool_manager.py](../modelhub_tools/tool_manager.py) |
| Java 业务适配与金额单位 | [modelhub_tools/model_hub_client.py](../modelhub_tools/model_hub_client.py) |
| 知识切片与检索 | [modelhub_tools/knowledge_base.py](../modelhub_tools/knowledge_base.py) |
| Embedding 与 Milvus | [storage/vector_store.py](../storage/vector_store.py) |
| Redis Memory、CAS 与画像 | [memory/conversation_memory.py](../memory/conversation_memory.py) |
| PostgreSQL 审计 | [storage/postgres_store.py](../storage/postgres_store.py) |
| 端到端评测 | [evaluation/evaluator.py](../evaluation/evaluator.py) |
| 性能监控 | [monitor/performance_monitor.py](../monitor/performance_monitor.py) |
| 标准 MCP Server | [modelhub_mcp/server.py](../modelhub_mcp/server.py) |
| 标准 MCP 业务适配 | [modelhub_mcp/service.py](../modelhub_mcp/service.py) |
| 容器与网关 | [Dockerfile](../Dockerfile)、[docker-compose.yml](../docker-compose.yml)、[config/nginx/nginx.conf](../config/nginx/nginx.conf) |
| Vue 对话页与用户 ID 契约 | [ChatView.vue](../../token-web/src/views/ChatView.vue)、[session.ts](../../token-web/src/lib/session.ts)、[api.ts](../../token-web/src/lib/api.ts) |
| Vite Java/Agent 代理 | [vite.config.ts](../../token-web/vite.config.ts) |
| Java 模型调用网关 | [GatewayService.java](../../token-java/src/main/java/com/hmdp/gateway/GatewayService.java)、[GatewayLedger.java](../../token-java/src/main/java/com/hmdp/gateway/GatewayLedger.java) |
| 模块执行流程总览 | [docs/project-execution-flow.md](project-execution-flow.md) |
| MCP/Skills 使用说明 | [docs/mcp-and-skills.md](mcp-and-skills.md) |

## 30. 面试前最后检查清单

- 能在 30 秒和 2 分钟内介绍项目；
- 能完整画出 `/chat`、Agent tool-use、RAG 和 Memory 四条链；
- 能明确解释内部 ToolManager 与标准 MCP 的区别；
- 能解释 Skill 为什么只是工作流指令；
- 能说清 tools_used 与 authoritative_tools_used；
- 能解释私有工具为什么由代码调用；
- 能手写 Redis CAS 竞态时序；
- 能给出 RAG 的召回、生成、安全和成本指标；
- 能指出至少 5 个当前实现边界及修复顺序；
- 能说明 58 项测试验证了什么、没有验证什么；
- 能回答项目为什么做、网关为何存在、GeneralAgent 何时降级、Agent 为何按这些职责拆分；
- 不虚构吞吐、准确率、费用下降或线上运行数据；
- 回答任何设计题时都落回“业务目标、权限边界、失败语义、可观测指标和验证方法”。

最后一句可以这样收束：

> 这个项目最有价值的部分不是堆叠了 Agent、RAG、MCP 和向量库，而是把每种能力放在合适的信任边界里：模型负责语义决策，代码负责权限和证据，评测与监控负责证明它长期有效。

## 31. 新增题单：多 Agent 与编排专项

> 本章开始合并新增题单中的重复问题。题目经过面试化改写，答案补充前文未展开的细节。

### 31.1 多智能体系统的目标是什么，为什么不使用一个通用 Agent

合并原题：1、3、4、32、33、53、55。

多 Agent 的目标不是模仿一个组织架构，而是把不同任务的**上下文、工具权限、证据要求、风险等级和输出规范**拆开：

- 模型选型关注质量、价格、上下文和延迟；
- 成本估算关注 Token 口径、单价和 Decimal 计算；
- 套餐订单关注库存、支付、到账和交易边界；
- API 支持关注鉴权、参数、错误码和安全排障；
- 风险复核关注证据与结论分离、人工审核；
- General 只做通用兜底。

如果只有一个通用 Agent，它的 system prompt 会越来越长，所有工具更容易被同时暴露，领域规则互相干扰，高风险问题也难以设置更严格的门禁。

当前实际运行的 Agent 类有：

| Agent | 主要职责 | 典型工具 |
|---|---|---|
| GeneralAgent | 通用咨询与受限知识问答 | knowledge_search，且仅部分通用意图开放 |
| ModelAdvisorAgent | 模型发现、比较和推荐 | 模型列表、搜索、详情、套餐、知识库 |
| CostOptimizerAgent | Token 与费用估算 | 模型实时价格、确定性成本计算、知识库 |
| QuotaOrderAgent | 套餐、库存、订单规则 | 套餐列表/详情/热门、知识库 |
| ApiSupportAgent | API/SDK/错误码排障 | 模型搜索/详情、知识库 |
| QuotaRiskAgent | 异常调用、盗用、争议复核 | 知识库 |

`MANUAL_REVIEW` 已有枚举、路由、Skill 和工具策略，但当前 Agent Pool 没有独立的人工审核 Agent 或工单系统，最终会回退到 GeneralAgent 并标记 `review_required`。

### 31.2 不同 Agent 只是提示词不同吗

不是，但也要准确说明：它们**当前复用同一个 BaseAgent、同一个配置的聊天模型和同一套 ToolLoop**，差异主要落在五层：

1. **角色 Prompt**：领域目标、禁止事项和输出口径不同；
2. **Skill**：注入对应的 SOP 和边界；
3. **工具白名单**：每类 Agent 只能看到必要工具；
4. **ToolPolicy**：首轮选择、锁定参数、强制证据和预算不同；
5. **审核语义**：风险/投诉/critical 更容易触发平台复核。

所以更准确的表述是：

> 当前是“同一执行内核 + 不同角色/Skill/Capability/Policy”的专业 Agent，而不是每个 Agent 部署一套不同模型或独立知识库。

### 31.3 AgentOrchestrator 具体编排哪些模块

合并原题：2、27、32、39、58。

`AgentOrchestrator` 是请求控制面，不是某个“更大的回答模型”。它依次负责：

```text
接收 Request
→ 缺少意图时调用 IntentRecognizer
→ 检测是否为复合领域问题
→ 单 Agent 路由或多 Agent 并行
→ 解析该 Agent 的 Project Skill
→ 生成最小 ToolPolicy
→ 克隆并隔离每个并行 Request
→ 选择同类型最佳 Agent 实例
→ 执行 AgentToolLoop
→ 失败关闭或受限降级
→ 合并文本、工具记录、审核标记和耗时
```

它内部可以拆成七个逻辑模块：

- IntentRecognizer：主意图、实体、紧急度；
- Collaboration Detector：补充识别复合领域；
- Static Router：意图到 Agent 类型；
- ProjectSkillRegistry：Agent 到 SOP；
- Policy Builder：Agent 到工具权限与证据要求；
- Agent Pool：同类型实例评分；
- Aggregator：回答与审计元数据合并。

### 31.4 一次线上请求如何从输入走到最终回复

面试时按十步回答即可：

1. FastAPI 校验**请求和 Bearer Header**，生成或复用 conv_id；
2. Token 或匿名 user_id 哈希成 memory subject；
3. MemoryManager 读取 Redis 最近消息/摘要、Milvus 情景记忆和画像；
4. 明确的私有订单/账户动作由 API 代码确定性预取；
5. IntentRecognizer 并行执行 LLM 与模板 Embedding，同步执行 Pattern，再融合主意图；
6. Orchestrator 选主 Agent/协作 Agent，加载 Skill 并生成 ToolPolicy；
7. AgentToolLoop 让模型在白名单内发起 tool_use，代码做 Schema、锁参、去重和预算校验；
8. RAG 工具走 rewrite、多路召回、权威过滤、去重、rerank；公共业务工具走 Java API；
9. tool_result 作为不可信数据回注，模型生成最终文本；强制证据失败则安全关闭；
10. 写入记忆并返回 intent、Agent、Skills、权威工具、轮次、耗时等元数据。

### 31.5 AgentOrchestrator 的“真值来源”是什么

Orchestrator 本身不是真值来源，它只组织证据。项目中的真值优先级是：

| 信息 | 权威来源 |
|---|---|
| 当前模型、价格、套餐、库存 | ModelHub Java 公共只读 API |
| 用户订单、账户、额度 | 携带认证主体的 Java 私有 API，并由后端校验资源归属 |
| 成本金额 | 实时原始分价 + Decimal 纯函数 |
| 平台规则与知识 | 受治理、带版本的知识库文档 |
| 用户偏好与历史 | Memory，仅作为上下文，不作为业务事实 |
| Skill | 工作流程和约束，不是真值 |
| LLM 参数知识 | 只能辅助解释，不能覆盖实时工具证据 |

高频答法：

> Orchestrator 解决“**去哪里取真值、谁有权取、失败后能不能回答**”，而不是自己制造真值。

### 31.6 多 Agent 的结果怎么合并

当前 `run_parallel` 会：

1. 以主意图路由结果作为 Primary Agent；
2. 把总工具调用预算精确分给多个 Agent；
3. 使用 `asyncio.gather(return_exceptions=True)` 并行；
4. 只保留成功响应；
5. 按 `[agent_type] + 文本` 拼接；
6. 去重 Skills 和工具记录；
7. 合并 authoritative、review_required、调用次数和最长轮次。

因此不能说当前已经做了“冲突消解”。更好的生产方案是让各 Agent 返回结构化字段：

```json
{
  "conclusion": "...",
  "evidence_ids": ["..."],
  "assumptions": ["..."],
  "risks": ["..."],
  "next_actions": ["..."]
}
```

再由低温度 Synthesizer 按证据优先级去重和处理冲突；若两个权威来源冲突，则不让模型自行裁决，而是标记待复核。

### 31.7 项目用了什么 Agent 框架，最重要的模块是什么

当前没有使用 LangChain/LangGraph，而是用 FastAPI、AsyncAnthropic 兼容 SDK、Pydantic、Redis、Milvus 和 PostgreSQL 构建薄层架构。

不用现成框架的收益：

- 可以精确控制 tool_use 协议、参数锁定和失败语义；
- 依赖更少，关键安全路径更容易审计和测试；
- 内部工具与标准 MCP 的边界清楚。

代价是连接生命周期、Tracing、持久图、重试、人机协作等都要自己实现。如果工作流进一步变成长期状态图、暂停恢复和人工节点，使用成熟图编排框架会更划算。

如果只能选一个最重要模块，不建议只说 RAG 或某个 Agent。更好的回答是：

> 最重要的是 Orchestrator、ToolPolicy 和 authoritative evidence 组成的控制面，因为它决定概率模型能做什么、事实来自哪里，以及失败后是否允许继续回答。

## 32. 新增题单：意图识别专项

### 32.1 三路融合识别器的目的、流程和输出是什么

合并原题：5、6、29、70。

它的目的不是检索知识，而是把开放式用户表达映射到固定业务意图集合，从而选择 Agent、Skill、工具权限和审核策略。

```text
用户消息 + 最近历史
├─ LLM：复杂语义与上下文
├─ Embedding：与固定 Few-shot 模板相似度
└─ Pattern：业务关键词兜底
→ 按置信度加权投票
→ 低于阈值（0.5）返回 OTHER
→ 第二次 LLM 提取实体
→ 关键词判紧急度
→ IntentResult
```

`IntentResult` 包含：

- `intent`：最终主意图；
- `confidence`：当前实现返回 LLM 原始 confidence，不是融合分数；
- `urgency`：LOW/MEDIUM/HIGH/CRITICAL；
- `entities`：order_id、model、provider、package、token_amount、budget、error_code；
- `reasoning`：LLM 的简短原因；
- `latency_ms`：识别耗时。

意图集合是根据业务能力、Agent 责任和风险边界人工设计的固定 `IntentCategory` 枚举，不是让模型自由创造标签。固定集合便于统计混淆矩阵、授权和回归测试。

### 32.2 70%/20%/10% 为什么这样设置

当前权重是工程初值，不是通过大规模超参数搜索得到的最优结论：

- LLM 0.7：主力处理上下文、省略和复杂语义；
- Embedding 0.2：用固定业务模板提供稳定校准；
- Pattern 0.1：提供低成本兜底，但降低误触发的决定权；
- Embedding 不可用时改为 LLM 0.85 + Pattern 0.15。

分数计算是 `weight × branch_confidence` 后按 IntentCategory 累加，最高分低于 0.5 时返回 OTHER。

面试时应主动补充：

> 这些比例应在标注意图集上通过网格/贝叶斯搜索和置信度校准确定，优化 Macro-F1、关键意图 Recall、误路由成本和延迟；尤其风险/私有意图要按业务成本设置不同阈值，而不是所有类别共用 0.5。

### 32.3 Agent 本身也依赖 LLM，为什么意图识别还用 LLM

LLM 意图分支的价值是理解“那价格呢”“这个错误怎么处理”等上下文表达；Embedding 和 Pattern 只能部分覆盖。

但质疑是成立的：当前意图 LLM、实体 LLM、Agent 和 Rerank 可能共享同一网关，故障和延迟相关。三路融合只能保证**路由信号**可降级，不能保证最终文本在 LLM 全挂时仍生成。

生产优化：

- 用蒸馏小分类器或**本地模型承担主意图**；
- 合并意图与实体为一次结构化输出；
- 对**高置信规则**走快速路径；
- LLM 仅处理**低置信和多轮歧义**样本；
- 不同故障域的模型/网关做降级；
- 即使最终生成失败，也返回**确定性安全错误**而不是错误事实。

### 32.4 复合问题如何处理，关键词会覆盖主意图吗

合并原题：31、67、68、69、86。

不会覆盖。实际顺序是：

1. 三路融合先得到一个 `req.intent`；
2. `_collaboration_targets` 以这个主意图为基础；
3. 再用模型、成本、套餐、API、风险关键词补充其他领域；
4. 多个目标并行执行；
5. Primary Agent 仍由主意图 `_route` 决定，而不是由关键词扫描顺序决定。

所以关键词的作用是提高**多标签召回**，不是替换主分类。

不过它确实存在误报。例如用户说“不要讨论支付，只讲 API”，`支付` 仍可能额外加入 QuotaOrderAgent；它也可能因词表缺失漏掉隐含领域。当前方案适合作为可解释的工程补丁，不适合领域无限扩张。

优化方式：

- 把主意图升级为 domain + action + risk 的多标签结构化分类；
- 加入**否定、引用和条件语义**；
- 给协作标签单独置信度阈值；
- 只有新增 Agent 能提供非重复能力时才并行；
- 用复合意图标注集统计 micro/macro F1 和额外 Agent 率；
- 对高风险私有动作仍由代码检查结构化 ID 和认证，不能只靠关键词。

### 32.5 意图边界模糊或识别错了会怎样

常见模糊边界包括：

- `QUERY` 与具体业务意图；
- `REQUEST` 与 TOKEN_PACKAGE；
- COST_ESTIMATION 与 USAGE_ANALYSIS；
- COMPLAINT、RISK 与 MANUAL_REVIEW。

误分类可能导致：

- 选错角色与回答风格；
- Skill/工具白名单不匹配；
- required evidence 未触发；
- 复合问题遗漏协作者；
- 高风险问题未正确标记审核。

当前仍有一定缓冲：**领域关键词可补协作者、General 可兜底，硬规则可在评测中发现风险**。但不能依赖最终 LLM 每次都“自我纠正”。

改进闭环：

1. 收集真实失败样本并人工标注；
2. 看每类 Precision/Recall/F1 和混淆矩阵；
3. 先修 taxonomy 与重叠定义，再补模板/规则；
4. 对低置信样本澄清或转人工；
5. 对关键意图提高 Recall 并加入行为门禁；
6. 使用 active learning 持续回流；
7. 版本化模板、模型和阈值。

当前 `learn()` 只把纠正样本加入进程内模板，不持久化，也不会清理已有结果缓存；它不是完整在线训练系统。

### 32.6 意图识别如何评测

使用带 ground truth 的 `IntentTestCase(message, expected_intent)`，逐条运行 Recognizer，计算：

- Accuracy；
- 每类 Precision、Recall、F1；
- Macro-F1；
- 每条 predicted、expected、confidence 和 reasoning。

还应补充：

- 复合意图的 multi-label F1；
- 高风险类别的加权 Recall；
- 置信度 ECE/Brier Score；
- 按短句、长句、错别字、多轮省略、否定表达切片；
- 路由后最终任务成功率。

当前 `IntentTestCase.context` 字段未真正传入 Evaluator 的 `recognize`，所以不能声称意图评测已覆盖多轮上下文。

### 32.7 意图缓存为什么可能导致“问 A 回 B”

当前缓存 key 只基于清洗后的当前消息前 200 字，不包含历史。例如两个会话都问“那这个呢”，即使前文分别讨论模型和套餐，也可能命中同一缓存结果。

修复应把这些信息纳入版本化 key： 

```text
normalized message
+ 最近历史摘要 hash
+ intent taxonomy version
+ template/model version
```

同时返回真正的融合分数和三路分项，便于线上定位到底是哪一路导致误判。

---

## 33. 新增题单：RAG、召回与重排序专项

合并原题：8、9、11～15、22～26、28、34～38、40、45、50～52、80、81、87。

### 33.1 项目中有几条检索链，它们分别解决什么问题

项目里存在三条容易被面试官混为一谈的向量链路：

| 链路 | 检索对象 | 发生时机 | 作用 | 是否直接生成最终答案 |
|---|---|---|---|---|
| 意图 Embedding | 当前问题与固定意图模板 | 路由阶段 | 给三路意图融合提供一个分类分数 | 否 |
| 业务知识 RAG | 用户查询与知识库分块 | Agent 决定使用 knowledge_search 后 | 给最终回答提供可引用的业务依据 | 是，作为上下文 |
| 情景记忆检索 | 当前问题与该用户的历史片段 | 意图识别之前 | 恢复追问所需的会话背景 | 是，作为上下文 |

因此，“检索到一条知识库 document 后怎么转换为意图”这个前提不成立。知识文档不会被转换成意图；意图分支比较的是一组固定意图模板，业务 RAG 检索到的 document 则保留为证据片段。

意图识别前发生的检索也不是业务知识分类检索，而是当前用户的情景记忆检索。它的目的是让“那价格呢”这类追问带上前文，不是提前决定业务 Agent。

### 33.2 知识是否必须打标，不同 Agent 是否使用不同知识库

当前知识集合是共享的，不是“账单 Agent 一个物理库、技术 Agent 一个物理库”。路由到不同 Agent 后，Agent 再根据 ToolPolicy 决定是否调用知识检索。

入库元数据会标准化 category 和 tags，但当前搜索主链没有按它们做强制过滤。所以面试时要诚实说明：

- 当前主要靠**向量相关性、权威性过滤和重排**；
- 标签已经进入元数据，但尚未成为完整的检索隔离或 ACL 机制；
- 不需要为了能检索而给每条知识手工打标，但生产环境应维护结构化元数据；
- 建议至少增加 domain、source、document_version、effective_time、tenant、ACL 和 trust_level，并让分块继承文档级元数据；
- 高风险账单、账户数据不应仅靠标签隔离，应通过认证后的私有 API 工具查询。

共享知识库的优点是减少重复文档和跨领域复用；风险是领域边界、权限和冲突更难治理。领域扩大后，可采用“共享物理集合 + 元数据过滤”，必要时再按租户或安全级别拆集合，而不是按每个 Agent 机械拆库。

### 33.3 数据入库、清洗和分块的实际实现

当前支持两类入口：知识文本新增接口和文件上传接口。文件侧支持 text、Markdown、JSON，大小上限为 10 MB，按 UTF-8 解码并忽略非法字符。

当前处理链：

1. 接收文本或上传文件；
2. 做基础类型、大小、空内容检查；
3. 按标点累计成约 500 字符的块；
4. 为标题、块序号和内容生成稳定 MD5 标识（doc_id）；
5. 将文本、向量和元数据写入 Milvus；
6. 相同标识先删除旧记录再插入，并执行 flush。

这里有几个必须主动说明的边界：

- 当前没有 overlap，跨块语义可能丢失；
- 一个超长且没有标点的句子可能超过 500 字符；
- 清洗只覆盖基础解码和切分，没有版面恢复、表格抽取、去页眉页脚、OCR 质量评估；
- 普通新增接口没有完整保留 category/tags，JSON 上传路径才可能携带更多元数据；
- 元数据序列化后若被直接截到字段上限，可能变成非法 JSON，读取时会退化为空对象；
- 图片和视频尚未纳入 RAG，没有 OCR、ASR、关键帧抽取或视觉向量。

生产化的分块策略不应只看固定字符数，而应根据文档结构和评测集选择：

- Markdown 按标题层级切分，保留父标题路径；
- FAQ 保持“问题 + 答案”原子性；
- API 文档按 endpoint 或操作切分；
- 表格保留表头与行关系；
- 长文本采用 token-aware chunk，并用小比例 overlap 保护跨块语义；
- 每块保存来源、页码、版本和生效时间，支持引用、回滚和删除。

分块大小和 overlap 没有普适最优值，应在真实问答集上联合评估召回率、上下文精度、答案忠实度、延迟和成本。

### 33.4 Embedding、查询重写、召回和最终合并

Embedding 有两种实现路径：

- 默认是稳定的字符一至三元组签名哈希向量（字符 n-gram + 哈希生成向量。），优点是无需下载模型、确定性强、离线可测试；缺点是它不是深度语义模型；
- 可选 SentenceTransformer/BGE 语义向量，查询侧可加检索指令并做归一化。

Milvus 使用 COSINE 相似度。向量维度与集合 schema 不一致时应快速失败；更换 embedding 模型或维度后必须重建索引，不能把不同向量空间混写。

一次业务 RAG 的实际流程是：

1. LLM 将原问题改写为最多三个子查询，同时始终保留原查询；
2. 最多四条查询并发召回，每路召回数至少为 max(top_k, 5)；
3. 只保留成功、权威且非 fallback 的结果；
4. 按内容哈希去重；
5. 用 LLM 对候选做 listwise 重排序；
6. 截取最终 Top-K 作为 Agent 的证据上下文。

所有召回结果不会都交给最终模型。Agent 工具默认 Top-K 为 3，通用搜索接口默认是 5，工具 schema 允许 1～10。最终结果合并依赖“原查询保底 + 多查询并发召回 + 内容去重 + 重排 + Top-K 截断”，不是把每路列表简单拼接。

查询重写并非每次都必要。它对口语、省略、多意图和同义表达有价值，但也会引入查询漂移和额外延迟。保留原问题就是防漂移措施。生产上可以根据问题长度、首轮召回置信度和歧义度决定是否重写：**高置信简单查询直接检索，低置信或复杂查询再扩展**。

### 33.5 LLM Rerank 用的是什么模型，为什么不直接塞全部文档

这里的 reranker 是可配置的 Anthropic 兼容 Chat 模型，不是 embedding 模型，也不是当前进程内的 cross-encoder。它通过异步 API 客户端调用；模型究竟部署在本地还是远端取决于 base URL 和网关配置，不能笼统声称“本地部署”。

实现上会把候选的序号、标题、相似度和约前 200 字符摘要交给模型，请模型返回相关性排序后的序号。解析失败时保留原向量顺序。当前实现仍有两个风险：摘要截断可能隐藏真正相关内容，模型返回缺失或重复序号时没有完整的补全与去重校验。

使用 LLM 重排的目的，是利用问题与多篇候选之间的语义关系做 listwise 判断，尤其适合复杂业务问法；但这不代表所有候选都应进入最终生成模型。全量塞入会造成：

- Token 成本和首字延迟显著增加；
- 长上下文中的 lost-in-the-middle；
- 低相关或冲突文档干扰答案；
- Prompt Injection 暴露面扩大；
- 引用和问题定位更困难。

面试官追问“为什么不用 cross-encoder”时，推荐这样回答：

> 当前实现选择 LLM listwise rerank，是为了快速复用现有模型网关并处理复杂语义；它不是唯一或最优方案。高流量生产链路更适合先用 BM25 + Dense 做混合召回，再用 RRF/MMR 去重增广，接一个本地或专用 cross-encoder 精排，只把少量歧义候选交给 LLM。这样能降低成本和延迟，也更容易离线评测。

当前项目没有 BM25 混合召回，也没有 cross-encoder，所谓“多路检索”主要是原查询和多个改写查询的并发 Dense Recall。不能把它包装成尚未实现的完整 Hybrid Search。

### 33.6 Top-K 怎么选，怎么证明 RAG 质量不是靠体感

当前 Top-K 和 500 字符分块是可用的工程初值，不是经过大规模严谨调参得到的最优值。正确的调参方式是建立**带答案与证据标注的 gold set（RAG 的标准测试集）**，联合搜索：

- chunk_size、overlap；
- 每路 recall_k、改写数量；
- 最终 context_k；
- Dense/BM25 权重；
- reranker 类型和阈值。

检索层看 Recall@K、MRR、nDCG、Context Precision/Recall；生成层看 Faithfulness、Answer Relevance、事实正确率和引用准确率；系统层同时看任务成功率、拒答正确率、P50/P95/P99 延迟、Token 与费用。

**当前项目已有端到端 Judge、硬规则和意图评测，但没有完整的 RAG gold set、证据级 Recall 和引用准确率统计，所以只能说“具备评测基础”，不能声称 Top-K 已被科学证明最优。**

建议的实验方法是：

1. 固定 embedding 和语料，做 chunk/overlap 网格实验；
2. 固定召回，比较无重排、LLM rerank、cross-encoder；
3. 按 API、账单、套餐、模糊追问等场景切片；
4. 记录质量、延迟、费用的 Pareto 前沿；
5. 使用版本化索引和离线回放，确认提升后再灰度。

### 33.7 知识冲突、无结果和“召回正确但模型说没找到”

真值优先级应是：**认证后的实时业务 API > 版本有效且权威的知识库 > 模型参数记忆**。模型常识与知识库冲突时，不能让模型自行投票；应按来源、版本、生效时间和业务责任域裁决，并在回答中说明依据。

如果 required knowledge 或关键工具没有权威结果，当前设计应 **fail closed**：明确说明无法核验，并引导重试或人工处理。普通、非关键问题可以使用**模型常识兜底**，但必须标注“未通过业务数据核验”，不能伪造成实时事实。

“向量已经召回正确文档，但模型仍说未找到”要逐层排查：

1. Milvus 原始 hit 是否真的包含该块，**向量维度和索引版本**是否一致；
2. 结果包装时是否**丢失正文或 metadata**；
3. authoritative/non-fallback 过滤是否误删；
4. 内容哈希去重是否发生碰撞或错误合并；
5. reranker 是否只因 200 字符预览看不到相关段落；
6. reranker 返回序号是否解析失败、缺失或重复；
7. 最终 Top-K 是否把正确块截掉；
8. 工具结果 8,000 字符截断或 Prompt 组装是否丢内容；
9. 最终模型是否忽略证据，或被冲突指令干扰。

生产日志应同时保留原始召回 trace 和最终证据 trace，包括 query/rewrite、稳定 chunk_id、版本、分数、过滤原因、rerank 前后次序、截断位置和引用。当前接口能暴露部分工具、权威性和延迟信息，但还没有把完整 RAG trace 作为统一的请求级可观测数据返回。

---

## 34. 新增题单：短期记忆、长期记忆与上下文治理

合并原题：16～18、46、47、81、83、90。

### 34.1 三层记忆分别是什么

代码中所说的“三层记忆”是：

| 层级 | 存储 | 主要内容 | 目标 |
|---|---|---|---|
| 工作记忆 | Redis List | 当前会话最近消息 | 保持短期多轮连续性 |
| 情景记忆 | Milvus | 可被语义检索的历史片段 | 跨较长历史找回相关经历 |
| 用户画像 | Milvus | 偏好、实体和相对稳定特征 | 个性化回答 |

此外还有 Redis Summary，用于压缩较老的工作记忆；PostgreSQL 保存原始对话、意图和工具轨迹用于审计，但当前不直接参与生成时的记忆检索。因此更精确的说法是“三层推理记忆 + 一个摘要压缩层 + 一个审计存储”。

### 34.2 每层的输入、输出和存储结构

工作记忆的输入是 **role、content、timestamp 和 metadata**。Redis key 形如 wm:{user_id}:{conversation_id}，用户与会话标识会做安全编码；使用 LPUSH 将最新消息放在列表头，TTL 为 24 小时。读取最多 20 条后反转为时间正序，输出最近会话消息。

当消息数量达到约 15 条时触发压缩：较旧消息交给 LLM 生成两到三句摘要，摘要写入 summary:{user_id}:{conversation_id}，同样设置 24 小时 TTL，工作列表保留最新 5 条。当前新旧摘要采用追加思路，长期可能继续增长，尚未实现 token-aware 的递归摘要。

情景记忆的输入是**通过并发安全提交后的会话片段**，同时保存 user_id、conversation_id 和 kind。查询时把当前问题向量化，在当前用户范围内按 COSINE 相似度取前 5 条；真正组装 Prompt 时最多使用前 3 条。输出是与当前问题语义相关的历史片段。

用户画像从最近约 10 条对话中让 LLM 提取 **preferences 和 entities JSON**，再以用户、会话和时间戳写入 Milvus。读取时先取有限候选，再按时间选择较新的画像。当前没有画像字段级 merge、CAS、版本冲突或全局严格最新保证，不能把它描述成成熟的主数据系统。

### 34.3 记忆如何进入一次请求

请求开始后，MemoryManager 先组装 MemoryContext，顺序大致是：

1. 历史摘要；
2. 与当前问题相关的情景记忆；
3. 用户画像；
4. 当前会话最近消息。

这些内容被序列化为上下文注入 Agent；最近约 5 条消息还会传给意图识别器，用于理解省略和追问。也正因为如此，意图识别前会发生向量检索，但检索对象是该用户的历史记忆，不是业务知识库。

回答成功并通过版本检查后，当前轮消息写回工作记忆和情景记忆；画像提取通常以后台任务执行。CAS 压缩确保只有观察到同一版本的请求能提交压缩结果，避免慢请求用旧快照覆盖新消息。第 12 节详细解释了这段并发控制。

### 34.4 有没有考虑上下文窗口爆炸

当前已经存在若干静态上限：

- 单条用户消息最多约 **20,000 字符**；
- 工作记忆读取**最多 20 条**；
- 达到约 15 条触发摘要，压缩后**保留 5 条**；
- 情景记忆**召回 5 条**，注入**最多 3 条**；
- 单个工具结果进入模型前**最多约 8,000 字符**；
- Agent 最多 **3 个工具轮次**、每轮**最多 4 个调用**；
- 最终模型输出上限约 **1,024 tokens**；
- rerank 候选正文预览**约 200 字符**。

这些限制能阻止无界增长，但当前没有统一的 token budget manager。字符数也不等于模型 token 数，多个 Agent、Skill、Memory、知识片段和工具结果叠加后仍可能超窗或挤掉关键证据。

生产优化应在 Prompt 组装前统一预算：

- 先预留 system、用户问题和输出 token；
- 按“安全规则 > 实时工具证据 > 知识证据 > 近期对话 > 相关历史 > 画像”分配优先级；
- 对每块记录 token 数、来源和截断原因；
- 用 MMR 或多样性约束避免多个相似记忆重复占位；
- 超预算时先删低价值片段，再摘要，不能从字符串末尾盲切；
- 将实际输入 token、被丢弃块和模型上下文利用率纳入 trace。

### 34.5 如果记忆错了怎么办

记忆只能是上下文线索，不能作为账单、余额、订单状态等权威事实。建议的优先级是：

> **实时认证业务数据 > 用户当前明确纠正 > 用户历史原话 > 模型从对话中推断的画像。**

当前风险包括：摘要和画像都可能吸收 Assistant 的错误内容；旧偏好没有 supersedes/tombstone；缺少来源、置信度、版本、失效时间和用户修订接口；相似度检索也可能召回“曾经正确、现在失效”的内容。

生产闭环应包括：

1. 每条记忆记录 source、created_at、valid_until、confidence 和 extractor_version；
2. 区分用户原话、系统事实和模型推断；
3. 用户纠正时写 supersedes 关系并给旧记录加 tombstone；
4. 提供查看、修改、删除和“忘记我”的能力；
5. 高风险事实每次回源，不从画像直接作答；
6. 检测新旧记忆冲突，低置信时询问用户而非擅自选择；
7. 支持按新版本抽取器从审计日志重建画像；
8. 对记忆污染、错误召回和删除生效做专项评测。

一句话回答：

> **我把记忆设计成可撤销、可追踪的弱证据，而不是永久真值；真正的业务事实必须回到权威工具验证。**

---

## 35. 新增题单：Skills、AI 编程工具与框架选型

合并原题：41～44、52、60～64、72、82、84。

### 35.1 这个项目里的 Skill 是什么

项目内 Skill 位于 .agents/skills/{skill-name}/SKILL.md。每个文件包含 YAML frontmatter 中的 **name、description**，**以及正文形式的专业工作流**。

它的定位是“角色可复用 SOP”，不是知识库：

- Skill 规定先检查什么、何时查工具、如何解释结果、哪些边界不能越过；
- RAG 保存可检索事实，内容可以频繁增加和更新；
- Tool 负责执行查询或动作；
- Agent 读取 Skill 后仍要由模型判断下一步，并受 ToolPolicy 约束。

当前专业 Agent 通常绑定一个主 Skill，GeneralAgent 不绑定；RiskReviewAgent 与 ManualReviewAgent 复用风险审查 Skill。一个 Skill 内可以有多条条件分支，例如 API troubleshooting Skill 会分别处理 401/403、404、429 和 5xx，但它仍是一份带分支的 SOP，不是四个独立知识库。

### 35.2 Skill 是怎么加载并进入 Agent 的

当前 ProjectSkillRegistry 在应用启动时扫描 .agents/skills，读取全部 SKILL.md，解析 name 和 description，并将正文缓存到进程内。AgentOrchestrator 再根据 Agent 类型静态解析所需 Skill，只把命中的 Skill 正文注入该 Agent 的 system prompt。

所以当前加载机制具有这些特点：

- 文件级发现、进程内缓存、Agent 级静态映射；
- 选择依据不是向量检索，也没有运行时语义搜索；
- 修改文件后通常需要重新加载或重启；
- 不会自动执行 Skill 中提到的操作；
- 尚未实现 scripts、references、assets 的按需加载；
- 没有完整的版本、依赖、冲突和权限声明。

项目早期最大的偏差正是：Skill 文本写着“调用某工具”，但第二条链只把它作为指令交给模型，没有真正的 MCP/tool-use 循环。后续加入 AgentToolLoop 和 ToolPolicy 后，模型才能产出结构化工具调用，框架执行工具、回填 observation，再由模型继续决策。这个改造说明：

> Skill 负责告诉模型“应该怎样工作”，工具循环负责让它“真的能工作”，权限策略负责限定“允许做什么”。

### 35.3 与 Codex Skills 的区别

根据 [OpenAI Codex Skills 官方文档](https://learn.chatgpt.com/docs/build-skills)，**Codex Skill 是包含指令、资源和可选脚本的可复用能力包，核心文件同样是 SKILL.md；还可以带 scripts、references、assets、agents/openai.yaml 等资源。**

Codex 采用**渐进披露**：

1. 初始上下文只暴露 Skill 的名称、描述和文件位置；
2. 用户显式调用或 Codex 判断任务匹配后，才完整读取对应 SKILL.md；
3. 执行过程中再按说明读取所需引用文件或运行脚本。

Codex 会从工作目录向仓库根扫描 .agents/skills，也支持用户级、管理员级和系统级 Skill。相比之下，本项目会在启动时把全部 Skill 正文读入进程，再通过固定 Agent 映射选择；**项目实现更简单、可控，但缺少渐进加载、丰富资源和通用发现能力。**

### 35.4 与 Claude Code、Trae 的区别

根据 [Claude Code Skills 官方文档](https://code.claude.com/docs/en/slash-commands)，Claude Code 也使用开放的 Agent Skills 结构：项目级 Skill 通常位于 .claude/skills/{name}/SKILL.md，可根据描述自动匹配，也可以通过 /skill-name 显式调用，并能携带支持文件或脚本。Claude Code 还提供调用控制、子 Agent 执行和动态上下文等扩展。

两者与本项目最核心的差别不是目录名称，而是运行时：

| 维度 | 本项目 | Codex / Claude Code |
|---|---|---|
| 场景 | ModelHub 客服业务 | 通用仓库级编码 Agent |
| 选择 | Agent 到 Skill 的静态映射 | 显式或按描述动态选择 |
| 加载 | 启动读取，选中后注入正文 | 渐进披露、按需读取资源 |
| 工具 | 内部 ToolRegistry 与 MCP 桥 | 文件、终端、搜索及扩展工具 |
| 权限 | ToolPolicy、认证和证据策略 | 沙箱、审批和工具权限 |
| 资源 | 当前主要是单一 Markdown | 可附带脚本、引用和资产 |

Trae 也公开提供 Rules/Skills 类能力，但其具体内部选择、缓存和上下文装载算法会随产品版本变化，公开材料不足以支持“底层完全如何实现”的断言。面试时应比较可观察行为和公开结构，不编造私有调度机制。

### 35.5 如何理解 AI 编程工具和 Claude Code 的原理

AI 编程工具不只是代码补全，而是一个面向仓库的 Agent Harness：

1. 收集用户任务、仓库规则、当前代码与环境；
2. 让模型制定或更新执行计划；
3. 通过搜索、文件读取、补丁、终端、测试和 Git 等工具观察并修改工程；
4. 将工具结果回填给模型，形成 observe-decide-act 循环；
5. 用沙箱、审批、命令白名单和 diff 控制风险；
6. 通过测试、静态检查和人工 review 验证结果；
7. Skill/MCP/插件提供可复用流程与外部能力。

Claude Code、Codex 等产品的模型只是决策核心，真正决定工程可用性的还包括**上下文构建、工具协议、权限系统、任务状态、结果压缩和验证闭环**。这与本项目给 Agent 补上 tool-use 循环的思路是一致的，只是目标领域和工具集合不同。

### 35.6 为什么没有用 LangChain，最重要的模块是什么

当前项目没有使用 LangChain，而是用 FastAPI、AsyncAnthropic、Redis、Milvus、PostgreSQL 和自定义编排器组合。这样做的理由不是“框架不好”，而是：

- 主链较明确，直接代码更容易解释每一步；
- 可以精确控制 Agent 路由、工具白名单、required evidence 和降级语义；
- 避免框架抽象掩盖同步阻塞、重试和错误传播；
- 面试项目更容易从源码证明行为。

代价也很明确：需要自己维护工具 schema、循环终止、trace、上下文预算、容错、并发和评测集成。生产团队若采用 LangGraph、Semantic Kernel 或其他 Agent 框架，仍需自己设计这些业务语义，框架不会自动解决真值和权限问题。

如果只能选一个最重要的模块，我会选“**编排与证据控制平面**”，它由 AgentOrchestrator、AgentToolLoop、ToolPolicy 和 authoritative/fallback 语义共同组成。因为它决定：

- 问题交给谁；
- 允许调用什么；
- 什么时候必须查真实数据；
- 哪些结果可以作为事实；
- 失败时是安全拒答还是继续生成。

模型、向量库和 Skill 都可替换；如果控制平面的语义不正确，系统会稳定地产生不可控答案。

### 35.7 最终回复是模型生成还是固定模板

正常回复由模型基于 **system prompt、Skill、Memory、知识和工具 observation** 生成。当前没有为每种业务问题维护一套完整固定话术。

但“模型生成”不等于完全自由发挥：

- 账单、订单、余额等私有事实必须来自认证后的确定性工具；
- ToolPolicy 可以要求某类意图必须调用指定工具；
-    system prompt 和 Skill 规定禁止承诺、转人工条件和回答边界；
- 关键工具失败时使用确定性错误或安全降级文案；
- 端到端评测的 forbidden claims 与硬规则阻止高分但违规的答案通过。

更成熟的客服生产方案可以让后端输出 decision_code 和结构化字段，再由经过法务/业务审核的模板渲染关键话术；模型只负责解释和个性化非关键部分。这样兼顾固定规则与自然表达。

### 35.8 像langchain、langgraph这些框架东西是很完善的，在开发过程中，项目哪些是可以用的，哪些是需要自己搭建的？

我会分成三类：直接复用的基础能力、基于框架定制的业务策略，以及独立实现的业务系统。

第一类是模型接入、工具定义、结构化输出，以及模型调用工具再继续生成的循环，这些可以使用 LangChain。多 Agent 的条件分支、并行执行、状态传递和中断恢复，可以使用 LangGraph。它们能替代我项目中一部分手写的工具循环和编排代码。[LangChain Agent 文档](https://docs.langchain.com/oss/python/langchain/agents)、[LangGraph 文档](https://docs.langchain.com/oss/python/langgraph/overview)

第二类是框架提供机制，但需要我们定义策略。比如框架可以执行条件路由，但模型选型、成本、订单这些意图怎么划分，低置信度怎么处理，什么时候让多个 Agent 协作，仍需要根据业务设计。RAG、记忆和工具权限也一样，需要结合自己的数据和规则配置、扩展。

第三类是业务系统本身。例如模型价格从哪里获取，成本怎么算，用户能查哪张订单，以及库存扣减、额度发放和超时补偿，都需要业务代码实现。框架可以调用这些接口，但业务正确性仍由 Java 后端保证。

所以，如果重新设计，我会优先复用框架的通用组件，把开发精力放在业务规则、数据质量、权限边界和评测上。当前项目中已经独立封装的 Java 接口和业务逻辑，也可以继续保留，通过工具或节点接入框架。

### 35.9 多agent框架有了解过哪些

我主要了解过 LangGraph、CrewAI、AutoGen 和 AgentScope。它们都能做多 Agent，但抽象和侧重点不同。

> 1. LangGraph：通过状态图组织执行流程
>
>    它把处理步骤组织成节点，通过边控制执行顺序和条件分支，支持共享状态、并行执行、持久化和人工介入。
>
>    对我的项目来说，可以把意图识别、业务查询、各个 Agent 和结果汇总建成节点，明确什么情况下进入哪个分支，比较适合业务流程需要可控、可恢复的场景。
>
> 2. CrewAI：通过角色和任务组织协作
>
>    它主要围绕 Agent、Task、Crew 和 Process 组织团队，例如让研究员收集资料、分析员分析、写作者输出报告。另外也有 Flows，用来控制事件、状态和执行流程。我的理解是，它比较方便把一个目标拆成不同角色负责的任务，快速搭建协作应用。
>
> 3. AutoGen：通过消息交互组织多 Agent
>
>     AutoGen 的 AgentChat 提供双 Agent 对话、群聊等协作模式；底层 Core 提供消息传递、事件驱动和运行时能力。
>
>    例如让一个 Agent 编写代码，另一个执行检查，再根据结果继续修改。不过当前官方已经将 AutoGen 转入维护模式，新项目建议评估 Microsoft Agent Framework。
>
> 4. AgentScope：通过消息和流水线组合 Agent
>
>    AgentScope 提供统一的消息交互机制，可以用消息中心让多个 Agent 共享消息，也支持顺序执行，以及把同一输入分发给多个 Agent 后收集结果。
>
>    对我的项目来说，“模型选型和成本分析分别处理同一个需求，再汇总回答”，就可以用这类编排能力实现。

---

## 36. 新增题单：评测链路与质量闭环专项

合并原题：16、19、25、26、38、73～79。

### 36.1 项目有哪两个闭环

项目里的“闭环”应拆成两条：

- 记忆闭环：读取 MemoryContext → 生成回答 → 通过版本检查后写回工作/情景记忆 → 异步更新画像；
- 质量闭环：测试集回放 → 收集路由、工具、知识和回答 → 硬规则检查 + LLM-as-Judge → 聚合失败类型 → 人工修改 Prompt、Skill、策略或数据后再回归。

第二条目前是“评测驱动的人工迭代”，不是在线自动改 Prompt。自动把 Judge 建议直接写回生产策略会放大评测偏差，也难以审计，因此当前保持人在环是合理的。

### 36.2 端到端评测链路如何执行

一条测试用例可以包含用户消息、期望答案要点、禁止出现的内容、期望意图、期望 Agent、期望工具、是否需要知识、是否要求业务数据，以及关键权威工具。

执行顺序：

1. 为一次评测运行创建隔离 namespace；
2. 同一多轮 case 复用会话状态，不同运行隔离 Redis key；
3. 调用真实主链，得到最终回答和执行轨迹；
4. 对路由、Agent、工具、知识和业务证据做确定性检查；
5. 用 Judge 对回答质量做结构化评分；
6. 应用硬门禁，计算 case 是否通过；
7. 聚合通过率、质量分、意图指标、错误类型和改进建议。

这种设计同时覆盖“回答听起来好不好”和“系统有没有按正确流程工作”。只看文本相似度无法发现模型编造余额，只看工具命中也无法判断解释是否清楚。

### 36.3 Judge 是打分还是二分类

Judge 对四个维度分别给 0～1 分：

| 维度 | 含义 |
|---|---|
| relevance | 是否真正回答用户问题 |
| accuracy | 是否与给定依据一致、没有明显错误 |
| completeness | 是否覆盖期望要点 |
| helpfulness | 是否清晰、可执行、对用户有帮助 |

四项等权平均得到 overall score。最终通过不是单纯二分类，也不是只看平均分，而是：

> passed = 硬规则通过 AND Judge 未失败 AND overall score ≥ 0.75

因此高分不能绕过业务门禁。例如回答很流畅，但包含禁止承诺、缺少 required business data、关键工具不是 authoritative，仍必须判失败。

### 36.4 打分标准有没有给示例

当前 Judge Prompt 给出了**每个维度的语言定义、0 与 1 的端点含义，以及要求返回的 JSON 结构示例**；但没有提供经过人工校准的多组 good/borderline/bad few-shot 评分样例。

这意味着输出格式相对稳定，但不同模型版本对 0.6、0.8 的边界可能漂移。生产改进应：

- 从真实样本中选取各场景锚点；
- 由两名以上标注员独立打分并仲裁；
- 把代表性的高、中、低样例加入 Judge Prompt；
- 计算 Judge 与人工的一致率、Spearman/Kendall 相关和阈值混淆矩阵；
- 固定 Judge 模型、Prompt 和版本，升级时做回归；
- 对高风险失败保留代码硬规则，不交给概率评分。

### 36.5 除了分数还返回什么

单条结果还会记录或聚合：

- 实际/期望 intent 和 Agent；
- collaborators 与协作状态；
- route_errors、tool_errors、critical_errors；
- 工具名、状态、是否命中缓存、是否 authoritative；
- 是否使用知识、知识条数和业务数据是否满足；
- expected points 缺失项和 forbidden claims；
- Judge reasoning、建议及解析错误；
- 总延迟以及知识、业务、工具等阶段信息。

这些字段让失败能归因到路由、数据、工具、模型或规则，而不是只得到一个无法行动的 0.72。

### 36.6 意图错了但最终答案很好，怎么统计

这种情况完全可能发生：GeneralAgent 兜底回答正确，关键词补充了协作者，或者模型靠常识碰巧答对。它不应被简单视为系统完全正确，因为未来换问题或需要私有数据时可能失败。

当前每条评测结果同时拥有 predicted/expected intent、route_errors、Judge 分数和 passed，所以离线可以筛出这些样本；但汇总报告还没有显式给出交叉指标。

建议新增：

- intent_wrong_answer_pass：意图错但答案通过；
- intent_right_answer_fail：意图对但答案失败；
- tool_wrong_answer_pass：工具路径错但文本碰巧通过；
- hard_rule_saved_cases：Judge 高分但被硬规则拦截；
- 各意图 confusion matrix 与最终任务成功率的二维表。

对 intent_wrong_answer_pass 应人工复盘：如果 taxonomy 本来就重叠，修标签定义；如果路由确实错了但模型侥幸答对，仍应修路由；如果最终任务不依赖该路由，可考虑简化类别。

### 36.7 意图识别自身怎么评测

意图评测使用带 ground truth 的 IntentTestCase，逐条运行 Recognizer，计算 Accuracy、每类 Precision/Recall/F1、Macro-F1，并保存预测类别、期望类别、置信度和 reasoning。

当前边界是 IntentTestCase 虽定义 context 字段，但 Evaluator 没有把它真正传入 recognize，所以不能声称现有测试已经评估多轮省略。还应加入：

- 多标签复合意图 F1；
- 风险、私有查询等关键类别的成本加权 Recall；
- 置信度校准 ECE/Brier Score；
- 短句、错别字、否定、引用、多轮追问等切片；
- 最终 Agent、工具和任务成功率，而不只看分类准确率。

### 36.8 如何证明整体回答质量

一个可信结论需要三层证据：

1. 组件级：Intent F1、Retrieval Recall@K、rerank nDCG、工具正确率；
2. 端到端：Judge + 硬门禁 + 人工抽检 + 任务成功率；
3. 线上：投诉率、转人工率、首轮解决率、拒答正确率、P95 延迟和成本。

**当前仓库具备离线端到端回放、四维 Judge、硬规则、意图指标和可观测元数据**，并有 57 个离线单元测试通过；**但默认评测集规模有限，尚未完成大规模人工标注、一致性分析、完整 RAG 证据评测和在线 A/B**。面试时这样说明，比只报一个高分更可信。

---

## 37. 新增题单：线上错误与投诉排查

合并原题：34、35、48～50、54、56。

### 37.1 用户反馈“问 A 回 B”，从哪里开始查

不要第一反应就改 Prompt。按请求链从前到后查，才能找到第一个发生偏差的节点：

1. **入口**：原始 message、conversation_id、user_id、认证主体、编码与截断是否正确；
2. **记忆**：最近消息、摘要、情景召回、画像是否串会话或召回旧事实；
3. **意图**：三路各自结果、融合分数、缓存 key、taxonomy/model/template 版本；
4. **路由**：Primary Agent、关键词补充的 collaborators、否定表达是否误触发；
5. **Skill/Policy**：加载了哪些 Skill，工具白名单和 required evidence 是否正确；
6. **工具**：参数是否从用户输入正确抽取，结果是 authoritative 还是 fallback，是否命中脏缓存；
7. **RAG**：原查询、改写、召回、过滤、去重、rerank、Top-K 与截断；
8. **Prompt**：多 Agent 合并时是否丢失来源，Memory/工具/知识谁覆盖了谁；
9. **生成**：模型版本、采样参数、超时重试和安全过滤是否改变回答。

这个项目有一个具体风险：意图缓存 key 只依赖当前短消息，不包含会话历史。“那这个呢”在不同上下文可能命中相同缓存，造成问 A 回 B。另一个风险是 Memory 在路由之前进入上下文，历史污染会同时影响意图和回答。

### 37.2 检索不到内容或知识库挂了怎么回答

先区分知识是 required 还是 optional：

- required：例如必须依据企业政策才能回答的问题，没有权威知识就**明确说明暂时无法核验，记录失败并建议重试**或转人工；
- optional：可以给一般性说明，但必须**标注没有通过项目知识库验证**；
- private fact：不能用知识库或模型常识替代，必须调用认证业务工具；
- 安全/投诉场景：保留解释边界并升级人工，不做未经授权的承诺。

知识库超时、空结果、解析失败和真正没有相关知识是不同错误码。生产系统应让工具返回结构化 status、error_type、authoritative 和 retryable，而不是都压成一句“未找到”，否则 Agent 与运维都无法正确决策。

### 37.3 正确文档已召回，但最终回答仍错误

第 33.7 节给出了完整的九层检查。线上最快的定位方式是对比三份数据：

- raw retrieval：Milvus 最初返回了什么；
- selected evidence：经过过滤、去重、重排和截断后真正进入 Prompt 的是什么；
- answer attribution：最终回答的每个关键事实来自哪个 tool/chunk/version。

如果 raw 正确而 selected 错，问题在过滤、重排或上下文预算；selected 正确而答案错，问题在 Prompt 冲突、生成遵循性或证据表达；两者都正确但用户仍认为错，需要检查知识版本、权限范围和业务定义是否过期。

当前 rerank 只看候选前约 200 字符，正确答案在后段时可能被误排；工具结果进入模型前也有约 8,000 字符上限。这两个截断点都必须记录在 trace 中。

### 37.4 当前有没有专门日志，够不够用

**当前回答与工具轨迹已经能暴露或记录 intent、Agent、collaborators、Skills、工具轮次、工具状态、cached、authoritative、工具延迟、权威结果数和总延迟；**PostgreSQL 还承担原始对话和审计数据保存。

但现状还不等于完整可观测性：

- ChatResponse 没有把 request_id 直接返回给调用方；
- RAG rewrite、每个 hit 的分数、过滤原因和 rerank 前后顺序没有统一串入请求 trace；
- 缺少跨 FastAPI、模型网关、Redis、Milvus、业务 API 的分布式 span；
- Prompt 版本、Skill 版本、索引版本和模型版本应作为统一标签；
- 日志必须对 token、API key、订单号和个人信息脱敏。

生产上应生成贯穿全链路的 request_id/trace_id，并让用户投诉工单携带该 ID。建议的 span 是：

> ingress → memory → intent → route → agent round → tool/MCP → RAG → synthesis → persistence

每个 span 记录耗时、状态、输入摘要、输出摘要和版本，但不明文保存秘密。

### 37.5 用户投诉答案不正确，标准处置流程

1. 固化原始请求、响应、时间、用户/会话和 trace_id；
2. 判断是否涉及资金、隐私、安全或合规，必要时立即人工接管；
3. 回放当时版本的 Prompt、Skill、模型、索引和工具响应；
4. 定位第一个错误节点，不只看最终文本；
5. 若知识错误，修源文档并重建受影响分块；若业务 API 错误，交由数据源修复；
6. 若路由/策略错误，补最小可复现评测样本；
7. 修复后跑组件与端到端回归，再灰度；
8. 给用户提供可解释更正，不泄露内部 Prompt 或安全规则；
9. 将事故按原因归类，跟踪是否重复发生。

一句适合面试的总结：

> 我会把“回答错”拆成输入、上下文、路由、证据、编排和生成六类问题，用同一个 trace 找到首个偏差点，再把该事故沉淀成回归用例。

---

## 38. 新增题单：高并发、延迟与项目难点

合并原题：56、82、84、88、89。

### 38.1 高并发下 Redis 或 Milvus 变慢，会不会拖垮路由

会。当前主链在意图识别之前先调用 MemoryManager 获取上下文，而 MemoryManager 使用同步 Redis/Milvus 客户端；在 async Web 主路径上，同步网络 I/O 可能阻塞事件循环。知识搜索虽然部分通过线程卸载，但缺少统一的全局 bulkhead 和 fan-out 预算。

因此即使意图分类模型很快，慢 Redis/Milvus 也可能让请求在路由前就排队。不能因为 FastAPI endpoint 是 async 就认为整条链都是非阻塞的。

优先改造顺序：

1. Redis 改用 redis.asyncio，Milvus 使用异步接口或有界线程池；
2. 将 summary、recent、episodic、profile 中相互独立的读取并行化；
3. 给每个依赖设置连接池、并发 semaphore、短超时和熔断器；
4. 建立请求总 deadline，各子阶段只能消费剩余预算；
5. Memory 超时后按风险场景降级为空上下文，不能无限等待；
6. 限制多 Agent、查询改写和工具调用的总 fan-out；
7. 使用按依赖隔离的 bulkhead，防止 Milvus 堵塞耗尽所有工作线程；
8. 监控队列长度、池等待时间、超时率和 P50/P95/P99。

### 38.2 一次请求这么多 LLM 调用，延迟从哪里来

最坏路径可能包含：

- 意图识别一次；
- 实体抽取一次；
- Primary/Collaborator Agent 各一至四轮；
- RAG 查询重写一次；
- RAG LLM rerank 一次；
- 达到阈值时的记忆摘要一次；
- 后台用户画像抽取一次。

多 Agent 并行只能降低独立分支的墙钟时间，不能消除每条分支内部的串行轮次。模型网关排队、冷启动、长 Prompt 和输出 token 也常比业务代码更慢。

可落地的优化：

- 合并意图与实体抽取为一次结构化调用；
- **高置信规则/embedding 直接路由，LLM 只处理低置信样本；**
- **简单查询跳过 rewrite，首轮召回足够好时跳过 rerank；**
- **用 cross-encoder 替代高频 LLM rerank；**
- **对独立 Agent 并发，但设置全局最大协作者数；**
- **对只读且稳定的工具结果做带版本和租户隔离的短 TTL 缓存；**
- **Summary 和 Profile 放入异步队列，不阻塞用户响应；**
- **精简 system、Skill 和历史上下文，统一 token budget；**
- 支持流式输出，但不要把“更早看到首 token”误当成总延迟下降；
- 记录每次模型调用的 queue、TTFT、generation、tokens 和重试。

### 38.3 超时和降级应该怎样设计

建议以总 deadline 驱动，而不是每层各自等待完整超时：

| 阶段 | 超时后的建议 |
|---|---|
| 画像/情景记忆 | 降级为空，保留近期会话 |
| 意图 LLM | 用 embedding + pattern，低置信走 General 或澄清 |
| 可选知识 | 标注未核验，回答通用信息 |
| 必需知识 | fail closed 或转人工 |
| 私有业务工具 | 禁止常识兜底，返回可重试错误 |
| collaborator | Primary 继续，但声明缺少的专业证据 |
| 最终模型 | 返回确定性安全错误并保留 trace |

降级必须保持事实语义。例如“工具失败”不能被包装成“账户没有订单”；timeout、empty、not_found 和 unauthorized 必须是不同状态。

### 38.4 开发过程中最难的点是什么

最难的不是把 Milvus、Redis 或模型 API 连起来，而是同时处理三件互相牵制的事：

1. **证据可信度**：模型何时必须查工具，fallback 能否当事实，不同来源冲突时听谁；
2. **并发一致性**：多请求同时写 Memory 时不能丢消息或用旧摘要覆盖新状态；
3. **质量与延迟平衡**：更多 Agent、改写、重排和 Judge 能提高覆盖，但会增加成本与尾延迟。

推荐用 STAR 这样回答：

> Situation：项目第二条 Agent 链最初只注入 Skill 指令，模型会说“我去查”，却没有真正执行工具，而且并发压缩记忆可能覆盖新消息。
>
> Task：在不让模型越权的前提下完成真实工具闭环，并保证多请求下记忆不丢。
>
> Action：我实现结构化 AgentToolLoop、ToolRegistry 和 ToolPolicy；区分 authoritative、fallback 与 required evidence；私有数据走确定性认证查询；Redis 侧用版本号和 CAS 提交压缩结果；再用硬规则和离线回放验证。
>
> Result：第二条链从静态 SOP 升级为可执行、可审计的工具循环，当前离线 57 个测试通过，也能暴露工具轮次与证据状态。
>
> Reflection：剩余工作是补 outbox、一致的全链路 trace、RAG gold set 和真实压测，不能把离线通过等同于生产容量结论。

这段回答既能体现技术深度，也不会把未完成的在线 A/B、压力测试或 exactly-once 语义说成已经实现。

---

## 39. 新增题单合并索引

原问题中存在跳号，下面按主题而非原顺序合并；同一问题可能同时出现在两个章节，因为面试追问会跨模块。

| 原题编号 | 合并后的主章节 |
|---|---|
| 1～4、21、27、32、33、39、53、55、58 | 第 3、4、31 节：总体链路、多 Agent 与编排 |
| 5、6、29～31、54、67～71、79、85、86 | 第 5、32、36.7 节：意图识别、复合路由与评测 |
| 8、9、11～15、22～26、28、34～38、40、45、50～52、80、81、87 | 第 9、10、33、37 节：RAG、Embedding、重排与故障 |
| 16～18、46、47、81、83、90 | 第 11、12、34 节：记忆、CAS 与上下文治理 |
| 19、25、26、38、73～79 | 第 16、36 节：端到端评测、Judge 与硬门禁 |
| 41～44、52、60～64、72、82、84 | 第 8、35 节：Skills、AI 编程工具与框架选型 |
| 48～50、54、56 | 第 22、33.7、37 节：线上排障与投诉处理 |
| 56、82、84、88、89 | 第 23、38 节：并发、延迟、架构取舍与难点 |

使用建议：

- 第一轮回答优先讲“目标—设计—链路—结果”，控制在 60～90 秒；
- 面试官追问参数或边界时，再展开本章对应小节；
- 对未实现能力使用“当前实现 / 已知边界 / 生产优化”三段式；
- 不要把可选配置说成默认行为，也不要把设计建议说成已经上线；
- 讲结论时尽量附源码模块、测试或 trace 字段作为证据。
