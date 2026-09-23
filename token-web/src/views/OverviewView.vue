<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import StateBox from '../components/StateBox.vue'
import UsageTable from '../components/UsageTable.vue'
import { api, date, messageOf, number } from '../lib/api'
import { session } from '../lib/session'
import type { Account, GatewayModel, Usage } from '../lib/types'
const models = ref<GatewayModel[]>([]), modelId = ref<number>(), account = ref<Account | null>(null), rows = ref<Usage[]>([])
const busy = ref(true), error = ref(''), accountError = ref(''), accountBusy = ref(false), page = ref(1), total = ref(0)
const available = computed(() => account.value ? Math.max(0, account.value.totalQuota - account.value.usedQuota - (account.value.reservedQuota || 0)) : 0)
const expired = computed(() => Boolean(account.value?.expireTime && new Date(account.value.expireTime).getTime() <= Date.now()))
async function loadAccount() { if (!modelId.value) return; accountBusy.value = true; accountError.value = ''; account.value = null; try { const rows = (await api<Account[]>(`/token-order/account/me?modelId=${modelId.value}`)).data || []; account.value = rows[0] || null } catch (e) { accountError.value = messageOf(e) } finally { accountBusy.value = false } }
async function loadUsage() { const result = await api<Usage[]>(`/gateway/usage?current=${page.value}`); rows.value = result.data || []; total.value = result.total || 0 }
async function load() {
  if (!session.token) { busy.value = false; return }
  busy.value = true; error.value = ''
  try { const result = await api<GatewayModel[]>('/gateway/models'); models.value = result.data || []; modelId.value ||= models.value[0]?.modelId; await Promise.all([loadAccount(), loadUsage()]) }
  catch (e) { error.value = messageOf(e) } finally { busy.value = false }
}
async function turn(delta: number) { page.value += delta; busy.value = true; error.value = ''; try { await loadUsage() } catch (e) { error.value = messageOf(e) } finally { busy.value = false } }
onMounted(load)
</script>
<template><div class="page-heading"><div><span class="eyebrow">YOUR WORKSPACE</span><h1>我的工作台</h1><p>掌握模型额度，了解每一次调用。</p></div><button class="btn btn-secondary" :disabled="busy" @click="load"><Icon name="refresh" :size="16" />刷新</button></div><StateBox v-if="!session.token" title="登录，开启你的模型工作台" description="在这里查看模型额度、用量和调用记录。"><button class="btn btn-primary" @click="session.loginOpen = true">登录 / 注册</button></StateBox><template v-else><StateBox v-if="error" :error="error" @retry="load" /><template v-else><div class="section-toolbar"><h2>模型额度</h2><select v-model="modelId" aria-label="选择额度账户的模型" @change="loadAccount"><option v-if="!models.length" :value="undefined">暂无网关模型</option><option v-for="model in models" :key="model.id" :value="model.modelId">{{ model.name }}</option></select></div><StateBox v-if="accountError" :error="accountError" compact @retry="loadAccount" /><div v-else class="stats-grid"><article class="stat-card primary-stat"><span>可用额度 <Icon name="bolt" :size="18" /></span><strong>{{ busy || accountBusy ? '…' : number(expired ? 0 : available) }}<small>Token</small></strong><p>{{ expired ? '账户已过期，请购买有效套餐' : account ? `有效期至 ${date(account.expireTime)}` : '购买套餐后，额度将在这里显示' }}</p></article><article class="stat-card"><span>已使用额度</span><strong>{{ busy || accountBusy ? '…' : number(account?.usedQuota) }}<small>Token</small></strong><p>当前模型账户累计使用量</p></article><article class="stat-card"><span>处理中预留</span><strong>{{ busy || accountBusy ? '…' : number(account?.reservedQuota) }}<small>Token</small></strong><p>请求结算后释放未使用的额度</p></article></div><div class="quick-links"><RouterLink to="/playground"><Icon name="chat" /><span>开始模型体验<small>把想法变成第一次调用</small></span><Icon name="arrow" :size="18" /></RouterLink><RouterLink to="/packages"><Icon name="box" /><span>补充模型额度<small>找到适合自己的套餐</small></span><Icon name="arrow" :size="18" /></RouterLink><RouterLink to="/keys"><Icon name="key" /><span>管理 API 密钥<small>连接你的应用与模型</small></span><Icon name="arrow" :size="18" /></RouterLink></div><section class="panel"><div class="panel-heading"><div><h2>调用记录</h2><p>按时间倒序展示 · 待核对请求可能仍有额度预留</p></div><span class="tag">共 {{ number(total) }} 条</span></div><StateBox v-if="busy" loading compact /><UsageTable v-else-if="rows.length" :rows="rows" /><StateBox v-else title="还没有模型调用" description="前往模型体验，完成一次真实调用。" compact /><div v-if="total > 10" class="pagination"><button class="btn btn-secondary btn-sm" :disabled="page === 1 || busy" @click="turn(-1)">上一页</button><span>第 {{ page }} 页</span><button class="btn btn-secondary btn-sm" :disabled="page * 10 >= total || busy" @click="turn(1)">下一页</button></div></section></template></template></template>
