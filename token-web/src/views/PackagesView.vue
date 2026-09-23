<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import StateBox from '../components/StateBox.vue'
import Modal from '../components/Modal.vue'
import { api, date, messageOf, money, number, post } from '../lib/api'
import { notify, requireLogin, session } from '../lib/session'
import type { Order, TokenPackage } from '../lib/types'
const route = useRoute()
const packages = ref<TokenPackage[]>([]), loading = ref(true), error = ref(''), packagePage = ref(1), packageTotal = ref(0)
const orders = ref<Order[]>([]), ordersBusy = ref(false), ordersError = ref(''), page = ref(1), total = ref(0)
const selected = ref<TokenPackage | null>(null), purchasing = ref(false), purchaseError = ref(''), activeOrder = ref<Order | null>(null), waitingOrder = ref(''), paying = ref(false)
const statusLabel: Record<number, string> = { 1: '待支付', 2: '已支付并发放', 4: '已取消' }
const setTimeout = window.setTimeout.bind(window)
let pollTimer: number | undefined, active = true
async function load() {
  loading.value = true; error.value = ''
  try { const result = await api<TokenPackage[]>(route.query.model ? `/token-package/model/${encodeURIComponent(String(route.query.model))}` : `/token-package/hot?current=${packagePage.value}`); packages.value = result.data || []; packageTotal.value = result.total || packages.value.length }
  catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}
async function loadOrders() {
  if (!session.token) return
  ordersBusy.value = true; ordersError.value = ''
  try { const result = await api<Order[]>(`/token-order/me?current=${page.value}`); orders.value = result.data || []; total.value = result.total || 0 }
  catch (e) { ordersError.value = messageOf(e) } finally { ordersBusy.value = false }
}
async function choose(pack: TokenPackage) {
  if (!requireLogin()) return
  selected.value = pack; purchaseError.value = ''; activeOrder.value = null; waitingOrder.value = ''; purchasing.value = true
  try { selected.value = (await api<TokenPackage>(`/token-package/${pack.id}`)).data } catch (e) { purchaseError.value = messageOf(e) } finally { purchasing.value = false }
}
async function pollOrder(id: string, attempt = 0) {
  if (!active || waitingOrder.value !== id) return
  try { const result = await api<Order>(`/token-order/${encodeURIComponent(id)}`); if (active && waitingOrder.value === id) { activeOrder.value = result.data; waitingOrder.value = ''; loadOrders() } }
  catch (e) {
    if (!active || waitingOrder.value !== id) return
    if (attempt < 9) pollTimer = window.setTimeout(() => pollOrder(id, attempt + 1), 1500)
    else purchaseError.value = `订单 ${id} 已受理，暂时未查询到最终结果。请到订单列表刷新查看；不要重复下单。${messageOf(e)}`
  }
}
async function buy() {
  if (!selected.value || purchasing.value || waitingOrder.value || activeOrder.value) return
  purchasing.value = true; purchaseError.value = ''
  try {
    const pack = selected.value
    const result = await api<string>(`/token-order/${pack.type === 1 ? 'seckill' : 'create'}/${pack.id}`, post())
    waitingOrder.value = String(result.data)
    notify('订单已受理，请确认订单后手动模拟支付。')
    await pollOrder(waitingOrder.value)
  } catch (e) { purchaseError.value = `${messageOf(e)} 若请求超时，请先刷新订单列表确认是否已创建。` }
  finally { purchasing.value = false }
}
async function pay() {
  if (!activeOrder.value || paying.value) return
  paying.value = true; purchaseError.value = ''
  try { await api(`/token-order/pay/${encodeURIComponent(activeOrder.value.id)}`, post()); notify('模拟支付成功，套餐额度已发放。'); activeOrder.value = (await api<Order>(`/token-order/${encodeURIComponent(activeOrder.value.id)}`)).data; loadOrders() }
  catch (e) { purchaseError.value = messageOf(e); loadOrders() } finally { paying.value = false }
}
function openOrder(order: Order) { selected.value = null; purchaseError.value = ''; waitingOrder.value = ''; activeOrder.value = order }
function close() { if (purchasing.value || paying.value) return; selected.value = null; activeOrder.value = null; waitingOrder.value = ''; window.clearTimeout(pollTimer) }
function orderPage(delta: number) { page.value += delta; loadOrders() }
function changePackagePage(delta: number) { packagePage.value += delta; load() }
onMounted(() => { load(); loadOrders() })
onBeforeUnmount(() => { active = false; window.clearTimeout(pollTimer) })
</script>
<template><div class="page-heading"><div><span class="eyebrow">PLANS & ORDERS</span><h1>让每一次调用，都有充足额度</h1><p>按模型选购 Token 套餐，管理你的订单与额度。</p></div><RouterLink v-if="route.query.model" to="/packages" class="btn btn-secondary" @click="packagePage = 1; setTimeout(load, 0)">查看全部套餐</RouterLink></div><div class="notice notice-inline"><Icon name="info" :size="18" /><span>当前购买流程使用<strong>模拟支付</strong>，不收取真实款项。套餐额度按模型使用；模型调用会消耗真实上游资源。</span></div><StateBox v-if="loading || error" :loading="loading" :error="error" @retry="load" /><StateBox v-else-if="!packages.length" title="暂无在售套餐" description="模型套餐准备好后会显示在这里。" /><div v-else class="package-grid"><article v-for="pack in packages" :key="pack.id" class="package-card"><div class="package-card-heading"><span class="tag" :class="{ 'tag-indigo': pack.type === 1 }">{{ pack.type === 1 ? '限时抢购' : '常规套餐' }}</span><span class="tiny muted">{{ pack.modelName || `模型 #${pack.modelId}` }}</span></div><h2>{{ pack.title }}</h2><p class="muted">{{ pack.subTitle }}</p><div class="package-price"><span>¥</span>{{ money(pack.payValue) }}<small>/ 套餐</small></div><div class="package-perks"><p><Icon name="check" :size="17" />{{ number(pack.tokenQuota) }} Token 额度</p><p><Icon name="check" :size="17" />{{ pack.validDays }} 天有效期</p><p><Icon name="check" :size="17" />{{ pack.type === 1 ? '活动库存及时间以下单校验为准' : '支付成功后发放额度' }}</p></div><p class="tiny muted package-rules">{{ pack.rules }}</p><button class="btn btn-primary full-width" @click="choose(pack)">{{ pack.type === 1 ? '查看抢购' : '选择套餐' }}<Icon name="arrow" :size="16" /></button></article></div><div v-if="!route.query.model && packageTotal > 10" class="pagination"><button class="btn btn-secondary btn-sm" :disabled="packagePage === 1 || loading" @click="changePackagePage(-1)">上一页</button><span>第 {{ packagePage }} 页</span><button class="btn btn-secondary btn-sm" :disabled="packagePage * 10 >= packageTotal || loading" @click="changePackagePage(1)">下一页</button></div><section class="panel orders-panel"><div class="panel-heading"><div><h2>我的订单</h2><p>订单编号、状态与额度发放记录</p></div><button class="btn btn-secondary btn-sm" :disabled="ordersBusy" @click="loadOrders"><Icon name="refresh" :size="15" />刷新</button></div><StateBox v-if="!session.token" title="登录后查看订单" description="订单只对当前登录用户展示。" compact><button class="btn btn-primary" @click="session.loginOpen = true">登录 / 注册</button></StateBox><StateBox v-else-if="ordersBusy || ordersError" :loading="ordersBusy" :error="ordersError" compact @retry="loadOrders" /><StateBox v-else-if="!orders.length" title="还没有订单" description="选择适合你的套餐，开始使用模型。" compact /><div v-else class="table-scroll"><table><thead><tr><th>订单编号</th><th>套餐</th><th>额度</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="order in orders" :key="order.id"><td class="mono">{{ order.id }}</td><td>#{{ order.packageId }}</td><td>{{ number(order.quotaAmount) }}</td><td><span class="tag" :class="{ 'tag-green': order.status === 2, 'tag-amber': order.status === 1 }">{{ statusLabel[order.status] || order.status }}</span></td><td class="nowrap">{{ date(order.createTime) }}</td><td><button class="text-button" @click="openOrder(order)">{{ order.status === 1 ? '模拟支付' : '查看详情' }}</button></td></tr></tbody></table></div><div v-if="total > 10" class="pagination"><button class="btn btn-secondary btn-sm" :disabled="page === 1 || ordersBusy" @click="orderPage(-1)">上一页</button><span>第 {{ page }} 页</span><button class="btn btn-secondary btn-sm" :disabled="page * 10 >= total || ordersBusy" @click="orderPage(1)">下一页</button></div></section><Modal v-if="selected || activeOrder" :title="activeOrder ? '订单详情' : '确认套餐'" :locked="purchasing || paying" @close="close"><template v-if="selected"><h3>{{ selected.title }}</h3><div class="order-summary"><p><span>适用模型</span><strong>{{ selected.modelName || `模型 #${selected.modelId}` }}</strong></p><p><span>套餐额度</span><strong>{{ number(selected.tokenQuota) }} Token</strong></p><p><span>有效期</span><strong>{{ selected.validDays }} 天</strong></p><p><span>套餐价格</span><strong>¥{{ money(selected.payValue) }}</strong></p><template v-if="selected.type === 1"><p><span>当前库存</span><strong>{{ selected.stock == null ? '以下单校验为准' : selected.stock }}</strong></p><p><span>活动开始</span><strong>{{ date(selected.beginTime) }}</strong></p><p><span>活动结束</span><strong>{{ date(selected.endTime) }}</strong></p></template></div><p class="muted small">{{ selected.rules }}</p></template><div v-if="activeOrder" class="order-summary"><p><span>订单编号</span><strong class="mono break-all">{{ activeOrder.id }}</strong></p><p><span>订单状态</span><span class="tag">{{ statusLabel[activeOrder.status] || activeOrder.status }}</span></p><p><span>额度</span><strong>{{ number(activeOrder.quotaAmount) }} Token</strong></p></div><div class="notice">模拟支付仅用于开发演示，不收取真实款项。后端需启用模拟支付配置，支付成功后才会发放额度。</div><p v-if="waitingOrder" class="muted small">订单 {{ waitingOrder }} 已受理，正在确认订单状态…</p><p v-if="purchaseError" class="error-text" role="alert">{{ purchaseError }}</p><div class="modal-actions"><button v-if="!activeOrder && !waitingOrder" class="btn btn-primary" :disabled="purchasing" @click="buy">{{ purchasing ? '正在处理…' : '确认创建订单' }}</button><button v-else-if="activeOrder?.status === 1" class="btn btn-primary" :disabled="paying" @click="pay">{{ paying ? '正在模拟支付…' : '确认模拟支付' }}</button><button v-else-if="activeOrder?.status === 2" class="btn btn-secondary" @click="close">完成</button></div></Modal></template>
