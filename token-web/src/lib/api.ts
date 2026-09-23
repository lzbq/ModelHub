import { logout, session } from './session'
import type { ApiResult } from './types'

export class ApiError extends Error { constructor(message: string, public status = 0) { super(message) } }

function validationDetail(result: any): string {
  if (typeof result?.detail === 'string') return result.detail
  if (!Array.isArray(result?.detail)) return ''
  return result.detail.map((item: any) => {
    const location = Array.isArray(item?.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : ''
    const message = typeof item?.msg === 'string' ? item.msg : ''
    return [location, message].filter(Boolean).join('：')
  }).filter(Boolean).join('；')
}

export async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (session.token) headers.set('Authorization', `Bearer ${session.token}`)
  try {
    const response = await fetch(path, { ...options, headers, signal: controller.signal })
    if (response.status === 401) { logout(); session.loginOpen = true; throw new ApiError('登录已过期，请重新登录。', 401) }
    const text = await response.text()
    let result: any
    try { result = text ? JSON.parse(text) : null } catch { throw new ApiError('服务返回了无效响应，请检查后端服务和代理配置。', response.status) }
    if (!response.ok) {
      throw new ApiError(result?.error?.message || result?.errorMsg || validationDetail(result) || `请求失败（${response.status}），请稍后重试。`, response.status)
    }
    return result as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw new ApiError('请求超时，请稍后查询执行结果。')
    throw new ApiError('暂时无法连接服务，请确认后端已启动，然后重试。')
  } finally { window.clearTimeout(timer) }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<ApiResult<T>> {
  const result = await request<ApiResult<T>>(`/api${path}`, options)
  if (!result || typeof result.success !== 'boolean') throw new ApiError('服务响应格式不正确。')
  if (!result.success) throw new ApiError(result.errorMsg || '操作未完成，请稍后重试。')
  return result
}
export const post = (body?: unknown): RequestInit => ({ method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
export const messageOf = (error: unknown) => error instanceof Error ? error.message : '发生未知错误，请重试。'

export function number(value?: number | string) { return new Intl.NumberFormat('zh-CN').format(Number(value ?? 0)) }
export function compact(value?: number) { return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value ?? 0) }
export function money(cents: number) { return (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }
export function date(value?: string) { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { hour12: false }) }
export const categories: Record<string, string> = { chat: '对话生成', reasoning: '深度推理', embedding: '向量嵌入', image: '图像生成' }
