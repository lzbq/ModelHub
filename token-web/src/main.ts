import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import CatalogView from './views/CatalogView.vue'
import OverviewView from './views/OverviewView.vue'
import PackagesView from './views/PackagesView.vue'
import KeysView from './views/KeysView.vue'
import ChatView from './views/ChatView.vue'
import GuideView from './views/GuideView.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/models' },
    { path: '/models', component: CatalogView, meta: { title: '模型广场', section: '探索' } },
    { path: '/overview', component: OverviewView, meta: { title: '我的工作台', section: '管理' } },
    { path: '/packages', component: PackagesView, meta: { title: '套餐与订单', section: '管理' } },
    { path: '/keys', component: KeysView, meta: { title: 'API 密钥', section: '管理' } },
    { path: '/playground', component: ChatView, props: { mode: 'model' }, meta: { title: '模型体验', section: '探索' } },
    { path: '/assistant', component: ChatView, props: { mode: 'agent' }, meta: { title: '智能助手', section: '探索' } },
    { path: '/guide', component: GuideView, meta: { title: '接入指南', section: '资源' } },
    { path: '/:pathMatch(.*)*', redirect: '/models' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
router.afterEach(to => { document.title = `${String(to.meta.title ?? '模型工作台')} · ModelHub` })
createApp(App).use(router).mount('#app')
