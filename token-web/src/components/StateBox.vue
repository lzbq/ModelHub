<script setup lang="ts">
import Icon from './Icon.vue'
withDefaults(defineProps<{ loading?: boolean; error?: string; title?: string; description?: string; compact?: boolean }>(), { title: '这里还没有数据', description: '' })
defineEmits<{ retry: [] }>()
</script>
<template>
  <div class="state-box" :class="{ 'state-compact': compact }" :aria-busy="loading">
    <span v-if="loading" class="spinner large" /><span v-else class="state-icon"><Icon :name="error ? 'info' : 'box'" :size="26" /></span>
    <h3>{{ loading ? '正在加载…' : error ? '暂时未能加载' : title }}</h3>
    <p>{{ loading ? '正在获取最新数据' : error || description }}</p>
    <button v-if="error" class="btn btn-secondary" @click="$emit('retry')"><Icon name="refresh" :size="16" />重新加载</button>
    <slot v-if="!loading && !error" />
  </div>
</template>
