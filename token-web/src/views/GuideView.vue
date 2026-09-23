<script setup lang="ts">
import { ref } from 'vue'
import Icon from '../components/Icon.vue'
import { notify } from '../lib/session'
const tab = ref<'curl' | 'python'>('curl')
const snippets = {
  curl: `curl http://localhost:8081/v1/chat/completions \\
  -H "Authorization: Bearer mh_your_platform_key" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: 73af343a-0d70-4dcc-82a8-bf6d9f0bbb35" \\
  -d '{
    "model": "modelhub-chat",
    "messages": [{"role": "user", "content": "你好，ModelHub"}],
    "max_tokens": 256,
    "temperature": 0.7
  }'`,
  python: `import os
import uuid
import requests

response = requests.post(
    "http://localhost:8081/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {os.environ['MODELHUB_API_KEY']}",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={
        "model": "modelhub-chat",
        "messages": [{"role": "user", "content": "你好，ModelHub"}],
        "max_tokens": 256,
        "temperature": 0.7,
    },
    timeout=90,
)
response.raise_for_status()
print(response.json()["choices"][0]["message"]["content"])`,
}
async function copy() { try { await navigator.clipboard.writeText(snippets[tab.value]); notify('示例代码已复制。') } catch { notify('无法访问剪贴板，请手动复制。', 'error') } }
</script>

<template>
  <div class="page-heading"><div><span class="eyebrow">QUICK START</span><h1>用一个接口，开始构建</h1><p>创建平台密钥，通过兼容 Chat Completions 的接口调用模型。</p></div><RouterLink to="/keys" class="btn btn-primary"><Icon name="key" :size="17" />创建 API 密钥</RouterLink></div>
  <div class="guide-grid">
    <aside class="guide-nav"><a href="#prepare">开始之前</a><a href="#request">发起调用</a><a href="#idempotency">安全重试</a><a href="#usage">计量与状态</a><a href="#limits">首版边界</a></aside>
    <article class="guide-content">
      <section id="prepare"><span class="step-number">01</span><h2>开始之前</h2><p>先登录并购买目标模型的 Token 套餐，然后在“API 密钥”页面创建平台密钥。密钥明文只显示一次，请存放在服务端环境变量中。</p><div class="notice"><Icon name="info" :size="18" />平台密钥以 <code>mh_</code> 开头，只能访问模型网关。登录会话和上游供应商密钥用途不同，不能互换。</div></section>
      <section id="request"><span class="step-number">02</span><h2>发起第一次调用</h2><p>请求体使用模型别名。默认示例为 <code>modelhub-chat</code>，实际可用模型以 <code>GET /v1/models</code> 返回为准。</p><div class="code-card"><header><div class="code-tabs"><button :class="{ active: tab === 'curl' }" @click="tab = 'curl'">cURL</button><button :class="{ active: tab === 'python' }" @click="tab = 'python'">Python</button></div><button class="icon-button" aria-label="复制代码" @click="copy"><Icon name="copy" :size="17" /></button></header><pre><code>{{ snippets[tab] }}</code></pre></div></section>
      <section id="idempotency"><span class="step-number">03</span><h2>用幂等键安全重试</h2><p>每次逻辑请求生成一个 <code>Idempotency-Key</code>。网络超时后，使用相同请求内容和相同键重试，网关不会重复调用或扣费。同一个键配合不同请求会返回 409。</p></section>
      <section id="usage"><span class="step-number">04</span><h2>理解计量状态</h2><div class="status-explain"><p><span class="tag">PENDING</span>已预留额度，正在等待结果。</p><p><span class="tag tag-green">SUCCEEDED</span>已按上游真实 usage 结算。</p><p><span class="tag tag-red">FAILED</span>请求已确认失败，预留已释放。</p><p><span class="tag tag-amber">NEEDS_RECONCILIATION</span>结果不确定，预留保持冻结，等待核对。</p></div><p>用量接口中的 <code>costYuan</code> 按目录价格估算。账户真正扣减的是输入与输出 Token 总数。</p></section>
      <section id="limits"><span class="step-number">05</span><h2>首版能力边界</h2><p>当前网关支持纯文本、非流式 Chat Completions。支持 <code>system</code>、<code>user</code> 和 <code>assistant</code> 消息；图片、音频、工具调用及 <code>stream: true</code> 会被明确拒绝。</p><p>模拟支付只用于本地演示，不收取真实款项。公开部署前还需接入支付回调、短信服务、管理员审核与供应商账单对账。</p></section>
    </article>
  </div>
</template>
