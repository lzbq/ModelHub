# ModelHub Web

Vue 3 + TypeScript + Vite 用户工作台，连接 Java 业务/模型网关和 Python Agent。

```powershell
npm ci
npm run dev
```

开发服务器监听 `127.0.0.1:5173`，代理 `/api` 到 Java `8081`、`/agent` 到 Python `8000`。生产构建使用 `npm run build`，同源代理示例见 `nginx.example.conf`。

登录会话只保存在 `sessionStorage`。不要在任何 `VITE_` 环境变量中存放上游供应商 Key 或平台 API Key。
