export interface ApiResult<T> { success: boolean; errorMsg?: string; data: T; total?: number }
export interface Model { id: number; name: string; provider: string; category: string; description: string; contextWindow: number; inputPrice: number; outputPrice: number; status: number }
export interface TokenPackage { id: number; modelId: number; modelName?: string; title: string; subTitle: string; rules: string; tokenQuota: number; payValue: number; validDays: number; type: number; status: number; stock?: number; beginTime?: string; endTime?: string }
export interface Account { id: string; modelId: number; totalQuota: number; usedQuota: number; reservedQuota?: number; expireTime?: string }
export interface Order { id: string; packageId: number; quotaAmount: number; status: number; createTime: string; payTime?: string }
export interface GatewayModel { id: string; modelId: number; name: string; provider: string; configured: boolean }
export interface ApiKey { id: string; name: string; prefix: string; status?: number; createdAt?: string; createTime?: string; lastUsedAt?: string; key?: string }
export interface Usage { requestId: string; modelId: number; model: string; status: string; promptTokens: number; completionTokens: number; totalTokens: number; costYuan?: number; createdAt: string; errorCode?: string }
export interface ChatMessage { role: 'user' | 'assistant'; content: string; tokens?: number; agent?: string; review?: boolean; tools?: string[] }
export interface ChatResult { id: string; model: string; choices: Array<{ message: { content: string } }>; usage?: { total_tokens: number } }
export interface AgentResult { response: string; conv_id: string; agent_type: string; tools_used?: string[]; review_required?: boolean }
