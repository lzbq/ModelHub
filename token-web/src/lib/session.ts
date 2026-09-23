import { reactive } from 'vue'

export const session = reactive({
  token: sessionStorage.getItem('modelhub.session') || '',
  user: null as null | { id: number | string; nickName: string },
  loginOpen: false,
  generation: 0,
})

export function setToken(token: string) {
  sessionStorage.setItem('modelhub.session', token)
  session.token = token
  session.generation++
}
export function logout() {
  sessionStorage.removeItem('modelhub.session')
  session.token = ''
  session.user = null
  session.generation++
}
export function requireLogin() {
  if (session.token) return true
  session.loginOpen = true
  return false
}

export const notices = reactive<Array<{ id: number; message: string; tone: 'success' | 'error' }>>([])
let noticeId = 0
export function notify(message: string, tone: 'success' | 'error' = 'success') {
  const id = ++noticeId
  notices.push({ id, message, tone })
  window.setTimeout(() => { const i = notices.findIndex(n => n.id === id); if (i >= 0) notices.splice(i, 1) }, 6000)
}
