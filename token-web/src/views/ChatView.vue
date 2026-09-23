<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import StateBox from '../components/StateBox.vue'
import { api, messageOf, request } from '../lib/api'
import { requireLogin, session } from '../lib/session'
import type { AgentResult, ChatMessage, ChatResult, GatewayModel } from '../lib/types'

const props = defineProps<{ mode: 'model' | 'agent' }>()
const models = ref<GatewayModel[]>([]), selected = ref(''), loadingModels = ref(false), modelError = ref('')
const messages = ref<ChatMessage[]>([]), input = ref(''), sending = ref(false), sendError = ref(''), convId = ref<string>()
const failed = ref<{ text: string; key: string }>(), scrollBox = ref<HTMLElement>()
const isModel = computed(() => props.mode === 'model')
const current = computed(() => models.value.find(model => model.id === selected.value))
const canSend = computed(() => Boolean(input.value.trim()) && !sending.value && (!isModel.value || Boolean(current.value?.configured)))

async function loadModels() {
  loadingModels.value = true; modelError.value = ''
  try {
    const result = await api<GatewayModel[]>('/gateway/models')
    models.value = result.data || []
    selected.value = models.value.find(model => model.configured)?.id || models.value[0]?.id || ''
  } catch (error) { modelError.value = messageOf(error) } finally { loadingModels.value = false }
}
function idempotencyKey() { return globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(36).slice(2)}` }
async function scroll() { await nextTick(); if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight }

async function submit(text = input.value.trim(), retryKey?: string) {
  if (!text || sending.value) return
  if (isModel.value && !requireLogin()) return
  if (isModel.value && !current.value?.configured) { sendError.value = '该模型尚未配置真实上游，请先配置 Java 网关。'; return }
  input.value = ''; sending.value = true; sendError.value = ''; failed.value = undefined
  messages.value.push({ role: 'user', content: text }); await scroll()
  try {
    if (isModel.value) {
      const key = retryKey || idempotencyKey()
      try {
        const result = await request<ChatResult>('/api/gateway/chat/completions', {
          method: 'POST', headers: { 'Idempotency-Key': key },
          body: JSON.stringify({ model: selected.value, messages: messages.value.filter(message => !message.agent).map(({ role, content }) => ({ role, content })), max_tokens: 512, temperature: 0.7 }),
        }, 90000)
        const content = result.choices?.[0]?.message?.content
        if (!content) throw new Error('模型没有返回可展示的文本。')
        messages.value.push({ role: 'assistant', content, tokens: result.usage?.total_tokens })
      } catch (error) { failed.value = { text, key }; throw error }
    } else {
      const result = await request<AgentResult>('/agent/chat', {
        method: 'POST', body: JSON.stringify({ message: text, user_id: String(session.user?.id ?? 'anonymous'), conv_id: convId.value }),
      }, 120000)
      convId.value = result.conv_id
      messages.value.push({ role: 'assistant', content: result.response, agent: result.agent_type, tools: result.tools_used, review: result.review_required })
    }
  } catch (error) {
    messages.value.pop()
    sendError.value = messageOf(error)
  } finally { sending.value = false; await scroll() }
}
function retry() { if (failed.value) submit(failed.value.text, failed.value.key) }
function reset() { messages.value = []; convId.value = undefined; failed.value = undefined; sendError.value = ''; input.value = '' }
watch(() => props.mode, () => { reset(); if (props.mode === 'model') loadModels() }, { immediate: true })
</script>

<template>
  <div class="page-heading chat-heading">
    <div><span class="eyebrow">{{ isModel ? 'MODEL PLAYGROUND' : 'MODELHUB ASSISTANT' }}</span><h1>{{ isModel ? '把模型放进真实对话' : '从需求到可执行方案' }}</h1><p>{{ isModel ? '通过平台网关调用真实上游，并按真实 Token 用量结算。' : '获取模型选型、成本、套餐、订单与 API 排障建议。' }}</p></div>
    <button class="btn btn-secondary" @click="reset"><Icon name="plus" :size="16" />新会话</button>
  </div>
  <section v-if="isModel && !session.token" class="chat-login"><StateBox title="登录后开始模型体验" description="模型体验会使用你的套餐额度，并产生一条真实调用记录。"><button class="btn btn-primary" @click="session.loginOpen = true">登录 / 注册</button></StateBox></section>
  <section v-else class="chat-layout">
    <aside class="chat-context">
      <template v-if="isModel">
        <h3>调用设置</h3><label>模型<select v-model="selected" :disabled="loadingModels"><option v-for="model in models" :key="model.id" :value="model.id">{{ model.name }}{{ model.configured ? '' : '（未配置）' }}</option></select></label>
        <StateBox v-if="modelError" :error="modelError" compact @retry="loadModels" />
        <div v-else class="model-status" :class="{ ready: current?.configured }"><span /><strong>{{ current?.configured ? '网关已就绪' : '等待配置上游' }}</strong><small>{{ current ? `${current.provider} · ${current.id}` : '暂无可用模型映射' }}</small></div>
        <p class="tiny muted">首版支持文本和非流式回答。每次发送都会预留额度，收到真实 usage 后完成结算。</p>
      </template>
      <template v-else><h3>可以这样问</h3><button v-for="sample in ['推荐一个适合中文知识库的模型', '每天 5000 次调用，估算月成本', 'API 返回 429 应该怎样排查？']" :key="sample" class="prompt-chip" @click="input = sample">{{ sample }}</button><p class="tiny muted">助手提供咨询与只读查询。支付、退款和额度调整需要在业务页面确认。</p></template>
    </aside>
    <div class="chat-card">
      <div ref="scrollBox" class="chat-messages" aria-live="polite">
        <div v-if="!messages.length" class="chat-empty"><span><Icon :name="isModel ? 'chat' : 'sparkle'" :size="30" /></span><h2>{{ isModel ? '发送第一条消息' : '你好，我是 ModelHub 助手' }}</h2><p>{{ isModel ? '回答来自配置的真实上游模型，用量将计入你的账户。' : '告诉我你的应用场景、调用量或遇到的问题。' }}</p></div>
        <article v-for="(message, index) in messages" :key="index" class="message" :class="message.role"><div class="message-avatar"><Icon :name="message.role === 'user' ? 'user' : isModel ? 'chat' : 'sparkle'" :size="17" /></div><div class="message-body"><div class="message-meta"><strong>{{ message.role === 'user' ? '你' : isModel ? current?.name || '模型' : 'ModelHub 助手' }}</strong><span v-if="message.agent">{{ message.agent }}</span><span v-if="message.tokens">{{ message.tokens }} Token</span></div><p>{{ message.content }}</p><div v-if="message.tools?.length" class="tool-list">调用工具：{{ message.tools.join('、') }}</div><div v-if="message.review" class="review-note">该回答建议由平台人工复核。</div></div></article>
        <article v-if="sending" class="message assistant"><div class="message-avatar"><span class="spinner" /></div><div class="message-body"><div class="message-meta"><strong>正在处理</strong></div><p class="muted">{{ isModel ? '正在调用模型并等待用量结算…' : '正在识别需求并调用相关 Agent…' }}</p></div></article>
      </div>
      <div v-if="sendError" class="chat-error"><Icon name="info" :size="17" /><span>{{ sendError }}<small v-if="failed">重试会复用同一个幂等键，避免重复扣费。</small></span><button v-if="failed" class="btn btn-secondary btn-sm" :disabled="sending" @click="retry">安全重试</button></div>
      <form class="composer" @submit.prevent="submit()"><textarea v-model="input" :disabled="sending" :placeholder="isModel ? '输入你想让模型完成的任务…' : '描述你的模型需求或问题…'" maxlength="12000" rows="3" @keydown.ctrl.enter.prevent="submit()" /><div class="composer-bottom"><span>Ctrl + Enter 发送</span><button class="btn btn-primary" :disabled="!canSend"><Icon name="send" :size="17" />{{ sending ? '发送中' : '发送' }}</button></div></form>
    </div>
  </section>
</template>
