<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './components/Icon.vue'
import LoginModal from './components/LoginModal.vue'
import { api } from './lib/api'
import { logout, notices, session } from './lib/session'
const route = useRoute()
const nav = [
  { path: '/models', label: '模型广场', icon: 'grid', group: '探索' },
  { path: '/playground', label: '模型体验', icon: 'chat', group: '探索' },
  { path: '/assistant', label: '智能助手', icon: 'sparkle', group: '探索' },
  { path: '/overview', label: '我的工作台', icon: 'dashboard', group: '管理' },
  { path: '/packages', label: '套餐与订单', icon: 'box', group: '管理' },
  { path: '/keys', label: 'API 密钥', icon: 'key', group: '管理' },
  { path: '/guide', label: '接入指南', icon: 'book', group: '资源' },
]
const userLabel = computed(() => session.user?.nickName || '已登录用户')
watch(() => session.token, async token => {
  if (!token) return
  try { const result = await api<{ id: number | string; nickName: string }>('/user/me'); if (session.token === token) session.user = result.data }
  catch { /* Individual views surface service failures; 401 is handled centrally. */ }
}, { immediate: true })
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/models" class="brand" aria-label="ModelHub 首页"><span class="brand-mark"><Icon name="box" :size="25" /></span><span>Model<span class="brand-light">Hub</span><small>让好模型，触手可及</small></span></RouterLink>
      <nav class="side-nav" aria-label="主导航"><template v-for="(item, i) in nav" :key="item.path"><div v-if="i === 0 || item.group !== nav[i - 1]?.group" class="nav-group">{{ item.group }}</div><RouterLink :to="item.path" class="nav-link"><Icon :name="item.icon" :size="19" />{{ item.label }}<span v-if="item.path === '/assistant'" class="nav-badge">AI</span></RouterLink></template></nav>
      <div class="sidebar-bottom"><div class="help-card"><Icon name="bolt" :size="22" /><h4>从想法，到第一次调用</h4><p>选择模型，配置密钥，让应用拥有 AI 能力。</p><RouterLink to="/guide">查看接入指南 <Icon name="arrow" :size="15" /></RouterLink></div><span class="sidebar-caption">MODELHUB · DEVELOPER CONSOLE</span></div>
    </aside>
    <div class="main-shell"><header class="topbar"><div class="breadcrumbs"><span>{{ route.meta.section }}</span><Icon name="chevron" :size="14" /><strong>{{ route.meta.title }}</strong></div><div class="top-actions"><RouterLink to="/guide" class="top-guide"><Icon name="book" :size="16" />开发文档</RouterLink><button v-if="!session.token" class="btn btn-primary btn-sm" @click="session.loginOpen = true"><Icon name="user" :size="16" />登录 / 注册</button><div v-else class="user-menu"><span class="avatar">{{ userLabel.slice(0, 1).toUpperCase() }}</span><span>{{ userLabel }}</span><button class="text-button" @click="logout">退出</button></div></div></header>
      <main id="main-content" class="page"><RouterView :key="`${route.path}:${session.generation}`" /></main>
      <footer class="page-footer"><span>ModelHub · 用一个平台，连接模型与应用</span><RouterLink to="/guide">开始构建 <Icon name="arrow" :size="14" /></RouterLink></footer>
    </div>
    <LoginModal v-if="session.loginOpen" />
    <div class="toast-stack" aria-live="polite"><div v-for="notice in notices" :key="notice.id" class="toast" :class="notice.tone"><Icon :name="notice.tone === 'success' ? 'check' : 'info'" :size="18" />{{ notice.message }}</div></div>
  </div>
</template>
