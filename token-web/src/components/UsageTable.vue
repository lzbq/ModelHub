<script setup lang="ts">
import { date, number } from '../lib/api'
import type { Usage } from '../lib/types'
defineProps<{ rows: Usage[] }>()
const labels: Record<string, string> = { PENDING: '处理中', SUCCEEDED: '已完成', FAILED: '失败', NEEDS_RECONCILIATION: '待核对' }
</script>
<template><div class="table-scroll"><table><thead><tr><th>模型 / 请求 ID</th><th>状态</th><th>输入 / 输出</th><th>总 Token</th><th>费用估算</th><th>调用时间</th></tr></thead><tbody><tr v-for="row in rows" :key="row.requestId"><td><strong>{{ row.model }}</strong><small class="mono truncated" :title="row.requestId">{{ row.requestId }}</small></td><td><span class="tag" :class="{ 'tag-green': row.status === 'SUCCEEDED', 'tag-red': row.status === 'FAILED', 'tag-amber': row.status === 'NEEDS_RECONCILIATION' }">{{ labels[row.status] || row.status }}</span><small v-if="row.errorCode">{{ row.errorCode }}</small></td><td>{{ number(row.promptTokens) }} / {{ number(row.completionTokens) }}</td><td>{{ number(row.totalTokens) }}</td><td>{{ row.costYuan == null ? '—' : `¥${Number(row.costYuan).toFixed(6)}` }}</td><td class="nowrap">{{ date(row.createdAt) }}</td></tr></tbody></table></div></template>
