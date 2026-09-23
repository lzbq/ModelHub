<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import StateBox from '../components/StateBox.vue'
import { api, categories, compact, messageOf, money, number } from '../lib/api'
import type { Model, TokenPackage } from '../lib/types'
const router = useRouter()
const models = ref<Model[]>([]), loading = ref(true), error = ref(''), query = ref(''), category = ref(''), page = ref(1), hasMore = ref(false)
const selected = ref<Model | null>(null), packages = ref<TokenPackage[]>([]), detailError = ref(''), detailBusy = ref(false)
const requests = ref(1000), inputTokens = ref(1000), outputTokens = ref(500)
const estimate = computed(() => selected.value ? ((inputTokens.value * selected.value.inputPrice + outputTokens.value * selected.value.outputPrice) * requests.value * 30 / 1_000_000 / 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '0')
async function load(reset = true) {
  if (reset) page.value = 1
  loading.value = true; error.value = ''
  try {
    const path = query.value.trim() ? `/ai-model/search?keyword=${encodeURIComponent(query.value.trim())}&current=${page.value}` : `/ai-model/hot?current=${page.value}${category.value ? `&category=${category.value}` : ''}`
    const result = await api<Model[]>(path)
    models.value = reset ? result.data || [] : [...models.value, ...(result.data || [])]
    hasMore.value = (result.data?.length || 0) >= 10
  } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}
function filter(value: string) { category.value = value; query.value = ''; load() }
async function details(model: Model) {
  selected.value = model; detailBusy.value = true; detailError.value = ''; packages.value = []
  try {
    const results = await Promise.all([api<Model>(`/ai-model/${model.id}`), api<TokenPackage[]>(`/token-package/model/${model.id}`)])
    if (selected.value?.id === model.id) { selected.value = results[0].data; packages.value = results[1].data || [] }
  } catch (e) { if (selected.value?.id === model.id) detailError.value = messageOf(e) } finally { detailBusy.value = false }
}
function more() { page.value++; load(false) }
onMounted(load)
</script>
<template>
  <section class="catalog-hero"><div class="hero-copy"><span class="eyebrow"><span class="live-dot" /> YOUR NEXT IDEA STARTS HERE</span><h1>为你的想法，找到合适的模型<span>。</span></h1><p>发现模型能力，比较调用成本。<br class="mobile-only" />从第一行代码，到你的下一个 AI 应用。</p><div class="hero-actions"><RouterLink to="/playground" class="btn btn-primary">开始体验 <Icon name="arrow" :size="17" /></RouterLink><RouterLink to="/guide" class="hero-link">阅读接入指南 <Icon name="chevron" :size="16" /></RouterLink></div></div><div class="hero-art" aria-hidden="true"><div class="orbit orbit-one" /><div class="orbit orbit-two" /><div class="art-core"><Icon name="box" :size="59" /></div><span class="orbit-label orbit-label-one"><Icon name="chat" :size="16" />Chat</span><span class="orbit-label orbit-label-two"><Icon name="bolt" :size="16" />Reasoning</span><span class="art-spark">✦</span><span class="art-dot" /></div></section>
  <div class="section-heading"><div><span class="eyebrow">MODEL EXPLORER</span><h2>探索模型</h2><p>不同任务，都有合适的选择。</p></div><form class="search-box" @submit.prevent="category = ''; load()"><Icon name="search" :size="19" /><input v-model="query" aria-label="搜索模型" placeholder="搜索模型名称或关键词…" /><button type="submit" class="text-button">搜索</button></form></div>
  <div class="filter-bar"><div class="tabs" role="group" aria-label="模型类别"><button :class="{ active: !category }" @click="filter('')">全部模型</button><button v-for="(label, key) in categories" :key="key" :class="{ active: category === key }" @click="filter(key)">{{ label }}</button></div><span class="tiny muted">按热度排序 · 价格 / 百万 Token</span></div>
  <StateBox v-if="loading && !models.length" loading />
  <StateBox v-else-if="error" :error="error" @retry="load()" />
  <StateBox v-else-if="!models.length" title="还没有找到相关模型" description="试试其他关键词，或选择全部模型。"><button class="btn btn-secondary" @click="filter('')">查看全部模型</button></StateBox>
  <div v-else class="model-grid"><article v-for="model in models" :key="model.id" class="model-card"><div class="model-card-top"><div class="provider-logo" :class="`provider-${model.provider.toLowerCase().replace(/[^a-z]/g, '')}`">{{ model.provider.slice(0, 1).toUpperCase() }}</div><span class="tag">{{ categories[model.category] || model.category }}</span></div><h3>{{ model.name }}</h3><span class="provider-name">{{ model.provider }}</span><p class="model-description">{{ model.description || '探索此模型的能力与适用场景。' }}</p><div class="model-context"><Icon name="book" :size="14" /><span>{{ compact(model.contextWindow) }} 上下文窗口</span></div><div class="model-prices"><div><span>输入价格</span><strong>¥{{ money(model.inputPrice) }}</strong></div><div><span>输出价格</span><strong>¥{{ money(model.outputPrice) }}</strong></div></div><button class="model-detail-button" @click="details(model)">查看模型详情 <Icon name="arrow" :size="16" /></button></article></div>
  <div v-if="hasMore && !error" class="load-more"><button class="btn btn-secondary" :disabled="loading" @click="more">{{ loading ? '正在加载…' : '加载更多模型' }}</button></div>
  <section class="bottom-banner"><div class="banner-icon"><Icon name="sparkle" :size="28" /></div><div><h3>还没决定选哪个模型？</h3><p>告诉智能助手你的场景，一起找到合适的模型和预算方案。</p></div><RouterLink to="/assistant" class="btn btn-secondary">和助手聊聊 <Icon name="arrow" :size="16" /></RouterLink></section>
  <Modal v-if="selected" :title="selected.name" wide @close="selected = null"><div class="detail-intro"><span class="tag">{{ selected.provider }}</span><span class="tag">{{ categories[selected.category] || selected.category }}</span><p>{{ selected.description }}</p></div><div class="detail-stats"><div><span>上下文窗口</span><strong>{{ number(selected.contextWindow) }}</strong></div><div><span>输入 / 百万 Token</span><strong>¥{{ money(selected.inputPrice) }}</strong></div><div><span>输出 / 百万 Token</span><strong>¥{{ money(selected.outputPrice) }}</strong></div></div><h3>估算你的月度成本</h3><div class="calculator"><label>每天请求数<input v-model.number="requests" type="number" min="0" /></label><label>单次输入 Token<input v-model.number="inputTokens" type="number" min="0" /></label><label>单次输出 Token<input v-model.number="outputTokens" type="number" min="0" /></label></div><div class="estimate"><span>预计 30 天费用 <small>按目录价格估算，实际以调用记录为准</small></span><strong>¥{{ estimate }}</strong></div><h3>可选套餐</h3><StateBox v-if="detailBusy || detailError" :loading="detailBusy" :error="detailError" compact @retry="details(selected!)" /><p v-else-if="!packages.length" class="muted">此模型暂无在售套餐。</p><div v-else class="package-options"><div v-for="pack in packages" :key="pack.id"><span><strong>{{ pack.title }}</strong><small>{{ number(pack.tokenQuota) }} Token · {{ pack.validDays }} 天有效</small></span><span>¥{{ money(pack.payValue) }}</span><button class="btn btn-secondary btn-sm" @click="router.push({ path: '/packages', query: { model: selected.id } })">查看套餐</button></div></div><div class="modal-actions"><button class="btn btn-primary" @click="router.push({ path: '/playground', query: { modelId: selected.id } })">体验这个模型 <Icon name="arrow" :size="16" /></button></div></Modal>
</template>
