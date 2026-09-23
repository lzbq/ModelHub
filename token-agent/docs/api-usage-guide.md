# ModelHub Agent API 使用指南

本文档介绍 FastAPI 服务对外暴露的全部 HTTP 接口，包含 Swagger 交互文档的使用方法、
每个接口的参数说明、可直接复制的请求体示例，以及 PowerShell 调用命令。

- 服务入口：`api/main.py`
- 默认地址：`http://127.0.0.1:8000`（端口由 `.env` 的 `API_PORT` 决定）
- 接口定义位置：`api/main.py`

---

## 1. 启动服务与打开交互文档

### 1.1 启动服务

```powershell
python api/main.py
```

或：

```powershell
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 1.2 打开文档界面

| 界面 | 地址 | 说明 |
|------|------|------|
| Swagger UI | http://127.0.0.1:8000/docs | 交互式文档，可直接填参数、发请求、看响应 |
| ReDoc | http://127.0.0.1:8000/redoc | 更适合阅读的接口文档 |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json | 原始接口描述数据 |

> 说明：根路径 `/` 没有定义路由，直接访问会返回 404，这是正常现象，请访问 `/docs`。

### 1.3 Swagger UI 基本操作

1. 点开某个接口条目；
2. 点击右侧 **Try it out**；
3. 填写参数 / 请求体；
4. 点击 **Execute**，下方即显示响应结果。

### 1.4 鉴权说明

本项目没有单独的 "Authorize" 按钮。需要鉴权的接口（`/chat`、`/model-hub/tool`、`/eval/run`）
在参数列表中会有一个名为 `authorization` 的请求头输入框，填写格式为：

```
Bearer 你的token
```

- `/chat` 的私有数据查询（订单、额度）必须带 Bearer Token，否则会提示未登录。
- `/model-hub/tool` 调用私有工具（`token_order` / `token_account`）需同时满足：
  `.env` 中 `MODELHUB_DEBUG_PRIVATE_TOOLS=true`，且带 Bearer Token，否则返回 403。
- `/eval/run` 需先在 `.env` 配置 `EVAL_ADMIN_TOKEN`，并在 `authorization` 头填 `Bearer 该token`，
  否则返回 503 / 401。

---

## 2. default 组

### 2.1 `GET /health` — 健康检查

无需任何参数，直接 Execute。返回服务是否就绪以及各 Agent 的运行统计。

### 2.2 `POST /chat` — 主对话接口（核心）

请求体字段（`ChatRequest`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 用户消息，必填，1~20000 字 |
| user_id | string | 用户标识，默认 `anonymous` |
| conv_id | string | 会话 ID，不填则自动生成 |
| model_id | int | 模型 ID，用于模型详情/额度查询 |
| package_id | int | 套餐 ID |
| order_id | int | 订单 ID，用于订单查询 |
| model_keyword | string | 模型搜索关键词 |
| category | string | 模型分类 |
| current | int | 分页页码，1~100，默认 1 |

**示例 ①：公开模型选型（无需 token）**

```json
{
  "message": "帮我推荐一个适合中文客服场景、性价比高的模型",
  "user_id": "demo1"
}
```

**示例 ②：带关键词搜模型**

```json
{
  "message": "有哪些适合长文本处理的模型？",
  "model_keyword": "qwen",
  "current": 1,
  "user_id": "demo1"
}
```

**示例 ③：成本估算**

```json
{
  "message": "模型1每天调用1000次，每次输入2000 token、输出500 token，一个月大概多少钱？",
  "model_id": 1,
  "user_id": "demo1"
}
```

**示例 ④：私有订单查询（需 `authorization: Bearer xxx`）**

```json
{
  "message": "查询订单 123 的支付状态",
  "order_id": 123,
  "user_id": "demo1"
}
```

**示例 ⑤：私有余额查询（需 `authorization: Bearer xxx`）**

```json
{
  "message": "我的余额还剩多少？",
  "user_id": "demo1"
}
```

> 注意：私有查询要求 `message` 中包含触发词（如"查询订单 / 支付状态 / 我的余额 / 剩余额度"等，
> 见 `api/main.py` 的 `_private_query_flags`），且必须带 Bearer Token。

PowerShell 等价命令：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/chat" `
  -ContentType "application/json" `
  -Body '{"message":"推荐一个中文客服模型","user_id":"demo1"}'
```

### 2.3 `GET /monitor` — 监控摘要

无参数。返回 Agent 成功率、工具统计、告警、优化建议。

### 2.4 `GET /metrics` — Prometheus 指标

无参数。返回 Prometheus 格式的纯文本指标（供 Prometheus 抓取）。

### 2.5 `POST /search` — 知识库检索

⚠️ `query` 与 `top_k` 是 **Query 查询参数**，不是请求体。在 Swagger 中直接填这两个输入框：

- `query`：`Token 套餐有哪些购买限制`
- `top_k`：`3`

PowerShell：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/search?query=Token套餐有哪些限制&top_k=3"
```

### 2.6 `POST /eval/run` — 运行评测

需要 `authorization: Bearer <EVAL_ADMIN_TOKEN>`。请求体留空 `{}` 即运行内置默认用例：

```json
{}
```

也可自定义用例（`intent_cases` / `dialog_cases` / `update_baseline`），详见 `EvalRunInput` 模型。

---

## 3. 知识库组

### 3.1 `POST /knowledge/add` — 批量导入文档

文档会自动切片（每片约 500 字）并存入向量库（默认 Milvus）。

```json
{
  "documents": [
    {"title": "模型选型规则", "content": "选型时综合考虑任务类型、质量、上下文长度、延迟和预算。"},
    {"title": "Token 套餐规则", "content": "限时套餐受库存、时间、限购和登录状态影响。"}
  ]
}
```

### 3.2 `POST /knowledge/upload` — 上传文件导入

在 Swagger 中点文件输入框选择文件，支持：

- `.txt` / `.md`：整个文件作为一篇文档，文件名作为标题；
- `.json`：数组格式 `[{"title": "...", "content": "..."}, ...]`。

文件大小限制 10MB。

### 3.3 `GET /knowledge/stats` — 查看片段总数

无参数。返回知识库当前文档片段总数。

### 3.4 `POST /knowledge/reset-modelhub` — 重置为默认知识

无参数。⚠️ 会**清空**现有知识库，再导入 ModelHub 默认业务知识，慎用。

---

## 4. ModelHub 组

### 4.1 `POST /model-hub/tool` — 调试只读工具

请求体格式固定为：

```json
{"tool_name": "工具名", "params": {}}
```

可用工具名：
`modelhub_hot_models`、`modelhub_search_models`、`modelhub_get_model`、
`modelhub_list_packages`、`modelhub_get_package`、`modelhub_hot_packages`、
`modelhub_estimate_cost`、`token_order`、`token_account`，
以及 6 个公开工具的短名别名：`model_hot`、`model_search`、`model_detail`、
`model_packages`、`package_detail`、`package_hot`。

**热门模型**

```json
{"tool_name": "modelhub_hot_models", "params": {"current": 1}}
```

**按关键词搜模型**

```json
{"tool_name": "modelhub_search_models", "params": {"keyword": "qwen"}}
```

**模型详情 / 实时价格**

```json
{"tool_name": "modelhub_get_model", "params": {"model_id": 1}}
```

**某模型可购套餐**

```json
{"tool_name": "modelhub_list_packages", "params": {"model_id": 1}}
```

**套餐详情 / 库存**

```json
{"tool_name": "modelhub_get_package", "params": {"package_id": 1}}
```

**成本估算（纯计算）**

```json
{
  "tool_name": "modelhub_estimate_cost",
  "params": {"model_id": 1, "input_tokens": 1000000, "output_tokens": 500000, "requests": 1000}
}
```

**私有工具（需 `MODELHUB_DEBUG_PRIVATE_TOOLS=true` + Bearer Token）**

```json
{"tool_name": "token_order", "params": {"order_id": 123}}
```

```json
{"tool_name": "token_account", "params": {"model_id": 1}}
```

---

## 5. 建议的上手顺序

1. `GET /health` 确认服务就绪；
2. `POST /knowledge/reset-modelhub` 或 `POST /knowledge/add` 灌入知识；
3. `GET /knowledge/stats` 确认导入成功；
4. `POST /search` 验证检索链路；
5. `POST /chat` 跑完整对话链路；
6. `POST /model-hub/tool` 单独调试某个工具；
7. `GET /monitor` 查看整体运行统计。

---

## 6. 常见问题

- **打开 `/` 返回 404**：根路径无路由，属正常现象，请访问 `/docs`。
- **`/docs` 页面空白**：确认服务已启动完成（日志出现 `Application startup complete`），
  且端口与 `.env` 的 `API_PORT` 一致。
- **私有查询提示未登录**：`/chat` 未带 Bearer Token，或 message 缺少触发词。
- **`/model-hub/tool` 调私有工具返回 403**：未开启 `MODELHUB_DEBUG_PRIVATE_TOOLS=true`。
- **`/eval/run` 返回 503**：未配置 `EVAL_ADMIN_TOKEN`。
