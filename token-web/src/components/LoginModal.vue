<script setup lang="ts">
import { ref } from 'vue'
import Modal from './Modal.vue'
import { api, post, messageOf } from '../lib/api'
import { notify, session, setToken } from '../lib/session'
const phone = ref(''), code = ref(''), error = ref(''), sent = ref(false), sending = ref(false), busy = ref(false)
async function sendCode() {
  if (!/^1\d{10}$/.test(phone.value)) { error.value = '请输入 11 位中国大陆手机号。'; return }
  sending.value = true; error.value = ''
  try { await api(`/user/code?phone=${encodeURIComponent(phone.value)}`, post()); sent.value = true }
  catch (e) { error.value = messageOf(e) } finally { sending.value = false }
}
async function login() {
  if (!/^1\d{10}$/.test(phone.value) || !/^\d{4,6}$/.test(code.value)) { error.value = '请填写有效手机号和验证码。'; return }
  busy.value = true; error.value = ''
  try {
    const result = await api<string>('/user/login', post({ phone: phone.value, code: code.value }))
    if (!result.data || typeof result.data !== 'string') throw new Error('登录响应缺少会话令牌。')
    setToken(result.data); session.loginOpen = false; notify('登录成功，欢迎来到 ModelHub。')
  } catch (e) { error.value = messageOf(e) } finally { busy.value = false }
}
</script>
<template><Modal title="登录 ModelHub" :locked="busy" @close="!busy && (session.loginOpen = false)"><p class="muted">登录后管理模型额度、创建密钥并开始调用。</p><form class="form-stack" @submit.prevent="login"><label>手机号<input v-model="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="请输入手机号" maxlength="11" required /></label><label>验证码<div class="input-action"><input v-model="code" inputmode="numeric" autocomplete="one-time-code" placeholder="输入验证码" maxlength="6" required /><button type="button" class="btn btn-secondary" :disabled="sending || busy" @click="sendCode">{{ sending ? '正在获取…' : sent ? '重新获取' : '获取验证码' }}</button></div></label><div class="notice">当前为开发登录：验证码写入 Java 服务日志，暂未接入短信服务。{{ sent ? '验证码已生成，请查看服务日志。' : '' }}</div><p v-if="error" role="alert" class="error-text">{{ error }}</p><button class="btn btn-primary full-width" :disabled="busy">{{ busy ? '正在登录…' : '登录 / 注册' }}</button><p class="tiny muted">首次登录将自动创建账号。会话仅保存在当前浏览器标签页。</p></form></Modal></template>
