# ModelHub

ModelHub 是一个面向大模型 API 的套餐交易与统一调用项目。Java 服务负责用户、模型目录、套餐订单、额度账户、平台 API Key 和模型网关；Python 服务负责多 Agent 咨询；Vue 工作台把这两条能力放进同一个用户界面。

## 项目结构

| 目录 | 作用 |
| --- | --- |
| `token-java` | Spring Boot 业务服务与 OpenAI Chat Completions 兼容网关 |
| `token-agent` | FastAPI + 自研多 Agent 编排、受控 Tool Use、RAG 与记忆 |
| `token-web` | Vue 3 + TypeScript 用户工作台 |
| `docs/frontend-gateway.md` | 本次前端、订单闭环和模型网关的实现说明 |

## 本地启动

1. 准备 MySQL、Redis 和 RocketMQ。
2. 新数据库执行 `token-java/src/main/resources/db/modelhub.sql`，随后执行 `token-java/src/main/resources/db/gateway-migration.sql`。已有数据库只执行迁移脚本。
3. 首次启动时复制 `token-java/.env.example` 为 `token-java/.env`，填写 `MYSQL_PASSWORD`、`MODEL_GATEWAY_API_KEY`，并按实际环境配置数据库与中间件。在 `token-java` 运行 `mvn spring-boot:run`。已有 `.env` 时直接编辑，避免覆盖现有配置。
4. 在 `token-web` 运行 `npm ci` 和 `npm run dev`，访问 `http://127.0.0.1:5173`。
5. 需要智能助手时，根据 `token-agent/.env.example` 创建本地 `.env`，按 [Agent API 使用指南](token-agent/docs/api-usage-guide.md)启动服务；前端会把 `/agent` 代理到 `127.0.0.1:8000`。Agent 的模型凭证和 Java 网关凭证分别配置。

模型网关的模型映射默认为 `modelhub-chat` → 数据库模型 `1` → `qwen3.5-flash`。请通过 `MODEL_GATEWAY_BASE_URL` 设置与你的百炼 Key 地域和业务空间对应的 OpenAI 兼容地址；API Key 默认留空，未配置时不会发送真实上游请求。配置方法见[前端与模型网关说明](docs/frontend-gateway.md)。

## 上传 GitHub

整个工作区使用一个仓库管理 Java、Agent 和前端源码。上传准备、旧 Agent 仓库备份、忽略规则及首次推送命令见 [GitHub 上传指南](docs/github-upload.md)。`token-agent/.agents/skills` 是应用运行时资源，必须随源码保留。

## 验证

```powershell
cd token-java
mvn test

cd ..\token-web
npm run build
```

模拟支付默认关闭。它只用于本地演示订单到账，不会收取真实款项；公开部署应替换为支付平台的服务端回调。
