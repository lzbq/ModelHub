"""
亮点：多 Agent 路由与编排

流程：
/chat 请求
  -> API 构造 Request
  -> AgentOrchestrator.run(req)
  -> 意图识别
  -> 判断是否多 Agent 并行
  -> 路由到具体 Agent，注入项目 Skill 并生成 ToolPolicy
  -> AgentToolLoop 在白名单和预算内执行 tool_use/tool_result，或走纯文本 LLM
  -> 检查是否需要人工审查
  -> 返回 OrchestratorResult

核心问题：多 Agent 情况下如何做 Routing？
路由策略（三层决策）：
  1. 意图路由 —— 根据 IntentCategory 直接映射到专属 Agent
  2. 性能路由 —— 同类 Agent 有多个时，选成功率最高、延迟最低的
  3. 降级路由 —— optional 路径可降级到受约束的 GeneralAgent；required evidence 失败关闭

并行协作：
  - 复杂问题（如“模型选型 + 月成本估算”）可同时派发给多个 Agent
  - 结果由 Orchestrator 合并后返回

人工审核机制：
  - 高风险、争议或无法确认的问题 → 标记为需平台侧确认/人工审核
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from agents.tool_use import (
    AgentToolLoop,
    ToolLoopError,
    ToolLoopResult,
    ToolPolicy,
    ToolUseRecord,
    authoritative_tool_names,
    executed_tool_names,
    merge_tool_records,
)
from core.intent_recognizer import IntentCategory, IntentRecognizer, UrgencyLevel
from core.project_skills import ProjectSkillRegistry
from modelhub_tools.tool_manager import MCPToolManager

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────────────

class AgentType(Enum):
    GENERAL   = "general"
    MODEL_ADVISOR = "model_advisor"      # 模型发现、比较与选型
    COST_OPTIMIZER = "cost_optimizer"    # Token 用量和成本优化
    QUOTA_ORDER = "quota_order"          # 套餐、订单与额度
    API_SUPPORT = "api_support"          # API、SDK 与错误排查
    QUOTA_RISK = "quota_risk"            # 刷购、Key 共享与异常调用
    MANUAL_REVIEW = "manual_review"  # 平台侧确认/人工审核标记（占位）


@dataclass
class AgentStats:
    """Agent 运行时统计，供 Monitor 和路由决策使用。
    保存某个 Agent 的调用总数、成功数、总耗时和监控惩罚值。
    """
    total:     int   = 0
    success:   int   = 0
    total_ms:  float = 0.0
    monitor_penalty: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.total if self.total else 0.0

    def routing_score(self) -> float:
        """
        综合成功率、延迟和惩罚项，计算该 Agent 的路由评分。
        路由评分：成功率高、延迟低的 Agent 得分高。
        """
        latency_score = 1.0 / (1.0 + self.avg_ms / 1000)
        base_score = self.success_rate * 0.7 + latency_score * 0.3
        return base_score * max(0.0, 1.0 - self.monitor_penalty)


@dataclass
class AgentResponse:             #表示单个 Agent 的返回结果
    agent_type:  AgentType
    content:     str
    success:     bool
    confidence:  float = 1.0     #置信度
    latency_ms:  float = 0.0     #耗时
    review_required: bool = False  # 是否需要平台侧确认/人工审核
    skills_used: List[str] = field(default_factory=list)#本次使用了哪些 Skill 工作流（如 modelhub-model-selection）
    tools_used: List[str] = field(default_factory=list)#实际调用了哪些工具（去重后的名称列表）
    authoritative_tools_used: List[str] = field(default_factory=list)#调用了哪些权威工具（返回了可信实时数据的工具，如 modelhub_get_model）
    tool_records: List[ToolUseRecord] = field(default_factory=list)#每次工具调用的详细记录（名称、状态、耗时、是否缓存等）
    tool_call_count: int = 0#实际有效工具调用次数（排除被拒绝/无效/重复/超预算的）
    tool_rounds: int = 0#工具循环进行了几轮
    tool_limit_reached: bool = False#是否触及了工具调用上限（max_rounds 或 max_calls）


@dataclass
class Request:
    message:     str
    user_id:     str
    conv_id:     str
    context:     str = ""        # 来自 MemoryManager 的格式化上下文
    history:     Optional[List[Dict[str, str]]] = None  # 对话历史，传给意图识别
    intent:      Optional[IntentCategory] = None        # 意图识别结果
    urgency:     Optional[UrgencyLevel]   = None        # 紧急程度
    entities:    Dict[str, List[str]] = field(default_factory=dict)  # 意图识别实体，供工具策略使用
    skill_instructions: str = ""                       # 可信项目 Skill，只注入 system prompt
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)
    tool_inputs: Dict[str, Any] = field(default_factory=dict)       # API 已校验的显式业务参数
    tool_context: Dict[str, Any] = field(default_factory=dict, repr=False)  # 服务端可信上下文，绝不进 prompt。repr=False 的意义：打印/日志 Request对象时自动隐藏这个字段，防止token/身份信息泄露到日志。
    prefetched_tool_records: List[ToolUseRecord] = field(default_factory=list)#私有数据预取记录
    tool_call_budget: Optional[int] = None                          # 并行协作时的调用预算分片。当多个 Agent 并行协作时，总工具调用预算被均分给各个 Agent

    #default_factory: 指定一个工厂函数，每次创建新实例时都会调用它来生成默认值（而不是共享同一个对象）
    #lambda: str(uuid.uuid4())[:8]: 匿名函数
    #每次创建类的新实例时，这个字段会自动生成一个唯一的 8 位随机字符串作为默认值
    request_id:  str = field(default_factory=lambda: str(uuid.uuid4())[:8])# 请求 ID

#表示编排器最终返回结果，包括响应文本、实际 Agent 类型、意图、是否需审核、总耗时。
@dataclass
class OrchestratorResult:
    request_id:  str#请求唯一 ID（8 位 UUID），用于日志追踪
    response:    str#最终文本回答（单 Agent 直接取，多 Agent 拼接）
    agent_type:  AgentType#实际使用的 Agent 类型
    intent:      Optional[IntentCategory]#意图识别结果
    collaborating_agent_types: List[AgentType] = field(default_factory=list)#并行协作的 Agent 类型列表
    skills_used: List[str] = field(default_factory=list)#本次使用了哪些 Skill 工作流（如 modelhub-model-selection）
    tools_used: List[str] = field(default_factory=list)#实际调用了哪些工具（去重后的名称列表）
    authoritative_tools_used: List[str] = field(default_factory=list)#调用了哪些权威工具（返回了可信实时数据的工具，如 modelhub_get_model）
    tool_records: List[ToolUseRecord] = field(default_factory=list, repr=False)#每次工具调用的详细记录（名称、状态、耗时、是否缓存等）
    tool_call_count: int = 0#总有效调用次数（预取 + Agent 循环）
    tool_rounds: int = 0#工具循环进行了几轮
    tool_limit_reached: bool = False#是否触及了工具调用上限（max_rounds 或 max_calls）
    review_required: bool = False#是否需要平台侧确认/人工审核
    latency_ms:  float = 0.0#总耗时


# ── 基础 Agent ────────────────────────────────────────────────────────────────

class BaseAgent:
    """所有 Agent 的基类，封装 LLM 调用和统计。"""

    agent_type: AgentType
    system_prompt: str

    def __init__(self, client: AsyncAnthropic, model: str):
        self._client = client
        self._model  = model
        self._tool_loop: Optional[AgentToolLoop] = None
        self.stats   = AgentStats() # 运行时统计

    def configure_tool_manager(self, manager: MCPToolManager) -> None:
        self._tool_loop = AgentToolLoop(manager)
    #主处理流程：记录开始时间、调用 LLM、更新成功统计、检测是否需要平台侧确认、返回 AgentResponse。
    async def handle(self, req: Request) -> AgentResponse:
        t0 = time.monotonic()
        self.stats.total += 1
        try:
            llm_result = await self._call_llm(req)#调用 LLM（可包含多轮只读工具调用）
            content = llm_result.content
            ms = (time.monotonic() - t0) * 1000
            self.stats.success += 1
            self.stats.total_ms += ms
            review_required = self._needs_review(content)#检测是否需要平台侧确认
            return AgentResponse(
                agent_type=self.agent_type,
                content=content,
                success=True,
                latency_ms=ms,
                review_required=review_required,
                tools_used=llm_result.tools_used,
                authoritative_tools_used=authoritative_tool_names(llm_result.records),
                tool_records=llm_result.records,
                tool_call_count=len([
                    record for record in llm_result.records
                    if record.status not in {"denied", "invalid", "duplicate", "budget_exceeded"}
                ]),
                tool_rounds=llm_result.rounds,
                tool_limit_reached=llm_result.limit_reached,
            )
        except ToolLoopError as ex:
            ms = (time.monotonic() - t0) * 1000
            self.stats.total_ms += ms
            records = list(ex.records)
            logger.error("%s 工具循环失败: %s", self.agent_type.value, ex)
            return AgentResponse(
                agent_type=self.agent_type,
                content="抱歉，当前无法完成所需的权威工具核验，请稍后重试。",
                success=False,
                latency_ms=ms,
                tools_used=executed_tool_names(records),
                authoritative_tools_used=authoritative_tool_names(records),
                tool_records=records,
                tool_call_count=len([
                    record for record in records
                    if record.status not in {"denied", "invalid", "duplicate", "budget_exceeded"}
                ]),
                tool_rounds=ex.rounds,
                tool_limit_reached=ex.limit_reached,
            )
        except Exception as ex:
            ms = (time.monotonic() - t0) * 1000
            self.stats.total_ms += ms
            logger.error(f"{self.agent_type.value} 处理失败: {ex}")
            return AgentResponse(
                agent_type=self.agent_type,
                content="抱歉，处理您的请求时出现问题，请稍后重试。",
                success=False,
                latency_ms=ms,
            )

    async def _call_llm(self, req: Request) -> ToolLoopResult:
        def _clean(s: str) -> str:
            return s.encode("utf-8", errors="ignore").decode("utf-8")#对文本做 UTF-8 清洗。

        messages = []
        if req.context:
            messages.append({"role": "user", "content": f"[背景信息]\n{_clean(req.context)}"})
            messages.append({"role": "assistant", "content": "好的，我已了解背景信息。"})
        messages.append({"role": "user", "content": _clean(req.message)})

        system = self._build_system_prompt(req)
        tool_loop = getattr(self, "_tool_loop", None)
        if tool_loop is not None and req.tool_policy.allowed_tools:
            return await tool_loop.run(
                client=self._client,
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=messages,
                policy=req.tool_policy,
                tool_context=req.tool_context,
            )

        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        texts = [
            str(getattr(block, "text", "")).strip()
            for block in resp.content
            if getattr(block, "type", None) == "text" and str(getattr(block, "text", "")).strip()
        ]
        if not texts:
            raise RuntimeError("模型没有返回可用文本")
        return ToolLoopResult(content="\n".join(texts))

    def _build_system_prompt(self, req: Request) -> str:

        if not req.skill_instructions:
            return self.system_prompt
        return f"{self.system_prompt}\n\n[项目内部 Skill 工作流]\n{req.skill_instructions}"

    def _needs_review(self, content: str) -> bool:
        """检测 Agent 是否建议平台侧确认/人工审核（简单关键词检测）。"""
        keywords = ["平台侧确认", "平台确认", "人工审核", "人工复核", "需审核", "无法确认", "无法处理"]
        return any(kw in content for kw in keywords)


class GeneralAgent(BaseAgent):
    agent_type    = AgentType.GENERAL
    system_prompt = (
        "你是 ModelHub 大模型 API 服务商城的智能助手。"
        "你可以帮助用户完成模型选型、成本估算、Token 套餐查询、订单额度说明和 API 使用排查。"
        "回答要自然、简洁、可执行；涉及真实业务状态时，优先依据背景信息中的 Java 后端查询结果。"
        "不要声称已执行套餐抢购、支付、额度调整或 API Key 操作，除非背景信息明确说明。"
    )


class ModelAdvisorAgent(BaseAgent):
    agent_type    = AgentType.MODEL_ADVISOR
    system_prompt = (
        "你是大模型选型 Agent。专注于模型发现、能力比较、上下文窗口、价格、延迟和适用场景。"
        "如果背景信息包含模型列表，必须依据真实名称、厂商、类别和价格进行比较，不能编造模型参数。"
        "Java 后端 inputPrice/outputPrice 原始单位是人民币分/百万 Token；展示人民币元时必须除以 100。"
        "如果缺少任务类型、调用量、质量要求或预算，只追问最关键的一项。"
    )


class CostOptimizerAgent(BaseAgent):
    agent_type    = AgentType.COST_OPTIMIZER
    system_prompt = (
        "你是 Token 成本优化 Agent。根据调用次数、平均输入/输出 Token、模型单价估算日/月成本。"
        "所有估算必须展示关键假设和计算口径，并区分输入、输出和缓存命中；数据不足时给出区间而不是伪精确值。"
        "必须优先使用背景中的 ModelHub 实时价格；inputPrice/outputPrice 原始单位是人民币分/百万 Token，换算成人民币元必须除以 100。"
        "输出结果前必须复核 Token 总量、分转元和乘除法，不得引用背景中不存在的外部价格或折扣。"
        "可以建议小模型分流、语义缓存、Prompt 精简和批处理，但不能虚构实际节省金额。"
    )


class QuotaOrderAgent(BaseAgent):
    agent_type    = AgentType.QUOTA_ORDER
    system_prompt = (
        "你是 Token 套餐与订单 Agent。专注于套餐库存、限购、抢购、支付、超时取消、额度到账和有效期。"
        "套餐抢购、支付、退款和额度调整是强事务操作，只能展示 Java 后端查询结果并引导用户在业务页面确认。"
        "Java 后端 payValue 原始单位是人民币分，展示人民币元时必须除以 100；tokenQuota 才是套餐 Token 数量。"
        "估算套餐可用时间时必须使用 tokenQuota ÷（日调用次数 × 每次输入输出 Token 总和），并复核数量级。"
        "回答要区分平台规则、当前查询状态、可能原因和下一步建议，绝不能承诺保证抢到或已经充值。"
    )


class ApiSupportAgent(BaseAgent):
    agent_type    = AgentType.API_SUPPORT
    system_prompt = (
        "你是大模型 API 技术支持 Agent。专注于 API Key、安全配置、SDK、请求参数、限流和错误码排查。"
        "先给最可能原因，再给按顺序可执行的检查步骤；不得要求用户粘贴完整 API Key。"
        "示例代码必须使用环境变量读取密钥，并明确模型名称应以平台真实列表为准。"
    )


class QuotaRiskAgent(BaseAgent):
    agent_type    = AgentType.QUOTA_RISK
    system_prompt = (
        "你是大模型额度与调用风控 Agent。专注于批量刷购、API Key 共享、盗用、调用量暴增和账号申诉。"
        "只能给出风险线索、规则解释和排查建议，不能仅凭单次数据直接认定违规。"
        "涉及封禁、扣除额度、退款争议或账号归属时，必须建议平台侧复核并标记人工审核。"
    )


# ── 编排器 ────────────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    多 Agent 编排器。

    路由逻辑（三层）：
      1. 意图 → Agent 类型映射
      2. 同类多实例时按 routing_score() 选最优
      3. 专属 Agent 失败时降级到 GeneralAgent
    """

    # 意图 → Agent 类型的静态映射（路由表） 把识别出的意图映射到对应 Agent 类型
    _INTENT_ROUTING: Dict[IntentCategory, AgentType] = {
        IntentCategory.MODEL_SEARCH: AgentType.MODEL_ADVISOR,
        IntentCategory.COST_ESTIMATION: AgentType.COST_OPTIMIZER,
        IntentCategory.TOKEN_PACKAGE: AgentType.QUOTA_ORDER,
        IntentCategory.USAGE_ANALYSIS: AgentType.COST_OPTIMIZER,
        IntentCategory.API_SUPPORT: AgentType.API_SUPPORT,
        IntentCategory.RISK:       AgentType.QUOTA_RISK,
        IntentCategory.COMPLAINT:  AgentType.QUOTA_RISK,
        IntentCategory.FEEDBACK:   AgentType.GENERAL,
        IntentCategory.MANUAL_REVIEW: AgentType.MANUAL_REVIEW,
        # 其余意图 → GENERAL（默认）
    }

    _INTENT_SKILLS: Dict[IntentCategory, tuple[str, ...]] = {
        IntentCategory.MODEL_SEARCH: ("modelhub-model-selection",),
        IntentCategory.COST_ESTIMATION: ("modelhub-cost-estimation",),
        IntentCategory.USAGE_ANALYSIS: ("modelhub-cost-estimation",),
        IntentCategory.TOKEN_PACKAGE: ("modelhub-quota-order",),
        IntentCategory.API_SUPPORT: ("modelhub-api-troubleshooting",),
        IntentCategory.RISK: ("modelhub-risk-review",),
        IntentCategory.COMPLAINT: ("modelhub-risk-review",),
        IntentCategory.MANUAL_REVIEW: ("modelhub-risk-review",),
    }
    #Agent 到 Skill映射表
    _AGENT_SKILLS: Dict[AgentType, tuple[str, ...]] = {
        AgentType.MODEL_ADVISOR: ("modelhub-model-selection",),
        AgentType.COST_OPTIMIZER: ("modelhub-cost-estimation",),
        AgentType.QUOTA_ORDER: ("modelhub-quota-order",),
        AgentType.API_SUPPORT: ("modelhub-api-troubleshooting",),
        AgentType.QUOTA_RISK: ("modelhub-risk-review",),
        AgentType.MANUAL_REVIEW: ("modelhub-risk-review",),
    }

    # 这是每种 Agent 的工具白名单——定义了每种 Agent 被允许调用哪些工具
    _AGENT_TOOLS: Dict[AgentType, tuple[str, ...]] = {
        AgentType.GENERAL: ("knowledge_search",),
        AgentType.MODEL_ADVISOR: (
            "modelhub_hot_models",
            "modelhub_search_models",
            "modelhub_get_model",
            "modelhub_list_packages",
            "knowledge_search",
        ),
        AgentType.COST_OPTIMIZER: (
            "modelhub_hot_models",
            "modelhub_search_models",
            "modelhub_get_model",
            "modelhub_estimate_cost",
            "knowledge_search",
        ),
        AgentType.QUOTA_ORDER: (
            "modelhub_list_packages",
            "modelhub_get_package",
            "modelhub_hot_packages",
            "knowledge_search",
        ),
        AgentType.API_SUPPORT: (
            "modelhub_search_models",
            "modelhub_get_model",
            "knowledge_search",
        ),
        AgentType.QUOTA_RISK: ("knowledge_search",),
        AgentType.MANUAL_REVIEW: ("knowledge_search",),
    }

    def __init__(
        self,
        api_key:  str,
        base_url: Optional[str] = None,
        model:    str = "claude-3-5-sonnet-20241022",
        embedding_backend: str = "stable",
        embedding_model: str = "",
        embedding_dim: int = 256,
        query_instruction: str = "",
        embedding_device: str = "",
        skills_dir: Optional[str] = None,
        tool_use_enabled: bool = True,
        tool_max_rounds: int = 3,
        tool_max_calls: int = 4,
        tool_max_parallel_calls: int = 3,
        tool_result_max_chars: int = 8000,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncAnthropic(**kwargs)

        self._intent_recognizer = IntentRecognizer(
            api_key=api_key,
            base_url=base_url,
            model=model,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            query_instruction=query_instruction,
            embedding_device=embedding_device,
        )
        self._skill_registry = ProjectSkillRegistry(skills_dir)#加载项目内置的 Skill 工作流。
        self._tool_use_enabled = tool_use_enabled
        self._tool_max_rounds = max(1, min(int(tool_max_rounds), 5))
        self._tool_max_calls = max(1, min(int(tool_max_calls), 10))
        self._tool_max_parallel_calls = max(1, min(int(tool_max_parallel_calls), 5))
        self._tool_result_max_chars = max(512, min(int(tool_result_max_chars), 20000))
        self._available_tool_names: set[str] = set()

        # Agent 池：每种类型可有多个实例（水平扩展）
        self._pool: Dict[AgentType, List[BaseAgent]] = {
            AgentType.GENERAL:   [GeneralAgent(client, model)],
            AgentType.MODEL_ADVISOR: [ModelAdvisorAgent(client, model)],
            AgentType.COST_OPTIMIZER: [CostOptimizerAgent(client, model)],
            AgentType.QUOTA_ORDER: [QuotaOrderAgent(client, model)],
            AgentType.API_SUPPORT: [ApiSupportAgent(client, model)],
            AgentType.QUOTA_RISK: [QuotaRiskAgent(client, model)],
        }

    def configure_tool_manager(self, manager: MCPToolManager) -> None:
        """把工具管理器绑定到所有 Agent 实例上，并记录实际可用的工具名集合。"""

        #收集所有 Agent 需要的工具名（去重）
        requested = tuple(dict.fromkeys(
            name for names in self._AGENT_TOOLS.values() for name in names
        ))
        #查询实际注册且可用的工具集合
        self._available_tool_names = {
            definition["name"] for definition in manager.get_tool_definitions(requested)
        }
        for agents in self._pool.values():
            for agent in agents:
                agent.configure_tool_manager(manager)

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def run(self, req: Request) -> OrchestratorResult:
        """
        处理一次请求的完整流程：
          意图识别 → 路由选 Agent → 执行 → 检查是否需平台侧确认 → 返回结果
        """
        t0 = time.monotonic()

        # 1. 意图识别（如果调用方已识别则跳过）
        if req.intent is None:#如果请求里没有意图，就调用意图识别器识别意图和紧急度。
            intent_result = await self._intent_recognizer.recognize(req.message, history=req.history)
            req.intent  = intent_result.intent
            req.urgency = intent_result.urgency
            req.entities = intent_result.entities

        # 复杂问题自动并行协作，例如同一句同时涉及模型推荐、成本和 Token 套餐。
        collaboration = self._collaboration_targets(req)#获取当前请求的所需的agent
        if len(collaboration) > 1:
            return await self.run_parallel(req, collaboration)

        # 2. 路由：选择 Agent 类型
        agent_type = self._route(req.intent, req.urgency)

        # 3. 执行（含降级）
        response = await self._execute(req, agent_type)

        # 4. 平台侧确认/人工审核检查
        review_required = False
        if response.review_required or req.urgency == UrgencyLevel.CRITICAL or req.intent == IntentCategory.MANUAL_REVIEW:
            review_required = True
            logger.warning(f"请求 {req.request_id} 需要平台侧确认: urgency={req.urgency}")
            # 生产环境：此处创建平台侧复核记录或审核任务

        records = merge_tool_records([req.prefetched_tool_records, response.tool_records])
        prefetch_calls = sum(
            1 for record in req.prefetched_tool_records
            if record.status not in {"denied", "invalid", "duplicate", "budget_exceeded"}
        )
        return OrchestratorResult(
            request_id=req.request_id,
            response=response.content,
            agent_type=response.agent_type,
            intent=req.intent,
            collaborating_agent_types=[response.agent_type],
            skills_used=response.skills_used,
            tools_used=executed_tool_names(records),
            authoritative_tools_used=authoritative_tool_names(records),
            tool_records=records,
            tool_call_count=prefetch_calls + response.tool_call_count,
            tool_rounds=response.tool_rounds,
            tool_limit_reached=response.tool_limit_reached,
            review_required=review_required,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    async def run_parallel(self, req: Request, agent_types: List[AgentType]) -> OrchestratorResult:
        """
        并行派发给多个 Agent，合并结果。
        适用于复杂问题（如同时涉及模型选型、成本估算和套餐规则）。
        """
        t0 = time.monotonic()
        # 主 Agent 由主意图决定，其他 Agent 只作为协作者。这样不会因为关键词扫描顺序而把套餐问题错误标记成 model_advisor。
        #① 确定主次 Agent
        preferred = self._route(req.intent, req.urgency)
        primary = preferred if preferred in agent_types else agent_types[0]
        ordered_types = [primary] + [agent_type for agent_type in agent_types if agent_type != primary]
        #创建协程对象，此时 tasks 是 [<coroutine object>, <coroutine object>, ...]
        # 这些协程处于"pending"状态，还没有真正运行
        # ② 均分工具预算
        total_budget = getattr(self, "_tool_max_calls", 4)
        base_budget, extra = divmod(total_budget, max(1, len(ordered_types)))
        budgets = [base_budget + (1 if index < extra else 0) for index in range(len(ordered_types))]# 余数分给前面的
        #③ 并行执行
        tasks = [
            self._execute(replace(req, tool_call_budget=budgets[index]), agent_type)
            for index, agent_type in enumerate(ordered_types)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # ④ 合并：拼接所有成功响应
        parts = []
        collaborators: List[AgentType] = []
        skills_used: List[str] = []
        response_record_groups: List[List[ToolUseRecord]] = []
        tool_call_count = 0
        tool_rounds = 0
        tool_limit_reached = False
        for r in responses:
            if isinstance(r, AgentResponse) and r.success:
                parts.append(f"[{r.agent_type.value}]\n{r.content}")# 拼接文本
                collaborators.append(r.agent_type)# 记录协作者
                for skill_name in r.skills_used:
                    if skill_name not in skills_used:
                        skills_used.append(skill_name)
                response_record_groups.append(r.tool_records)
                tool_call_count += r.tool_call_count
                tool_rounds = max(tool_rounds, r.tool_rounds)
                tool_limit_reached = tool_limit_reached or r.tool_limit_reached

        combined = "\n\n".join(parts) if parts else "抱歉，所有 Agent 均处理失败。"
        review_required = (
            any(isinstance(r, AgentResponse) and r.review_required for r in responses)#任一需要审核则为 True
            or req.urgency == UrgencyLevel.CRITICAL
            or req.intent == IntentCategory.MANUAL_REVIEW
        )

        records = merge_tool_records([req.prefetched_tool_records, *response_record_groups])
        tool_call_count += sum(
            1 for record in req.prefetched_tool_records
            if record.status not in {"denied", "invalid", "duplicate", "budget_exceeded"}
        )
        return OrchestratorResult(
            request_id=req.request_id,
            response=combined,
            agent_type=primary,
            intent=req.intent,
            collaborating_agent_types=collaborators,
            skills_used=skills_used,
            tools_used=executed_tool_names(records),
            authoritative_tools_used=authoritative_tool_names(records),
            tool_records=records,
            tool_call_count=tool_call_count,
            tool_rounds=tool_rounds,
            tool_limit_reached=tool_limit_reached,
            review_required=review_required,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # ── 路由逻辑 ──────────────────────────────────────────────────────────────

    def _route(self, intent: Optional[IntentCategory], urgency: Optional[UrgencyLevel]) -> AgentType:
        """
        三层路由决策：
          1. 意图映射
          2. 紧急度覆盖（CRITICAL 直接标记为需平台侧确认）
          3. 默认 GENERAL
        """
        if urgency == UrgencyLevel.CRITICAL:
            return AgentType.MANUAL_REVIEW

        if intent and intent in self._INTENT_ROUTING:
            target = self._INTENT_ROUTING[intent]
            # 如果目标类型有可用实例则使用，否则降级
            if target in self._pool and self._pool[target]:
                return target

        return AgentType.GENERAL

    def _collaboration_targets(self, req: Request) -> List[AgentType]:
        """
        判断是否需要多个 Agent 并行协作。

        意图识别通常只返回一个主意图；这里用领域关键词补充检测复合问题，
        例如“推荐适合知识库的模型并估算月成本”需要选型和成本 Agent 同时处理。
        """
        msg = req.message.lower()
        targets: List[AgentType] = []

        model_kws = ["模型", "选型", "推荐", "比较", "上下文", "推理", "embedding"]
        cost_kws = ["成本", "预算", "估算", "多少钱", "费用", "调用量", "token 数"]
        order_kws = ["套餐", "额度", "秒杀", "抢购", "订单", "支付", "到账", "库存", "有效期"]
        api_kws = ["api", "sdk", "key", "错误码", "429", "401", "限流", "请求格式"]
        risk_kws = ["刷购", "共享", "盗用", "被盗用", "key 被盗", "异常调用", "风控", "批量账号", "投诉", "申诉"]

        if req.intent == IntentCategory.MODEL_SEARCH or any(kw in msg for kw in model_kws):
            targets.append(AgentType.MODEL_ADVISOR)
        if req.intent in (IntentCategory.COST_ESTIMATION, IntentCategory.USAGE_ANALYSIS) or any(kw in msg for kw in cost_kws):
            targets.append(AgentType.COST_OPTIMIZER)
        if req.intent == IntentCategory.TOKEN_PACKAGE or any(kw in msg for kw in order_kws):
            targets.append(AgentType.QUOTA_ORDER)
        if req.intent == IntentCategory.API_SUPPORT or any(kw in msg for kw in api_kws):
            targets.append(AgentType.API_SUPPORT)
        if req.intent in (IntentCategory.RISK, IntentCategory.COMPLAINT) or any(kw in msg for kw in risk_kws):
            targets.append(AgentType.QUOTA_RISK)

        # 保持顺序去重，并只返回当前有实例的 Agent 类型。
        #将 targets 列表中的每个元素作为字典的键（key）
        #由于字典的键必须是唯一的，重复的元素会自动被去除,所有键对应的值都是 None
        deduped = list(dict.fromkeys(targets))
        return [agent_type for agent_type in deduped if self._pool.get(agent_type)]

    def _skill_names_for_execution(self, req: Request, agent_type: AgentType) -> tuple[str, ...]:
        """根据当前 Agent 类型，确定本次执行需要加载哪些 Skill 工作流。"""
        by_agent = self._AGENT_SKILLS.get(agent_type)
        if by_agent:
            return by_agent
        if req.intent is not None:
            return self._INTENT_SKILLS.get(req.intent, ())
        return ()

    def _tool_policy_for_execution(self, req: Request, agent_type: AgentType) -> ToolPolicy:
        """负责为每次 Agent 执行精确配置一份 ToolPolicy。"""
        #阶段一：前置拦截
        if not getattr(self, "_tool_use_enabled", False):#工具总开关关闭？
            #是 → 检查是否需要权威数据
            has_private_evidence = any(record.authoritative for record in req.prefetched_tool_records)
            evidence_required = agent_type in {
                AgentType.MODEL_ADVISOR,# 模型选型 → 需要实时价格
                AgentType.COST_OPTIMIZER,# 成本优化 → 需要实时价格
                AgentType.API_SUPPORT,# API 排查 → 需要模型详情
                AgentType.QUOTA_RISK,# 风控 → 需要平台规则
                AgentType.MANUAL_REVIEW, # 人工审核 → 需要平台规则
            } or (agent_type == AgentType.QUOTA_ORDER and not has_private_evidence)#套餐订单 → 如果已有私有数据预取结果就不需要了，没有才需要
            #evidence_required=True → 上层 _execute() 会直接返回"工具不可用，请稍后重试"
            #evidence_required=False → 上层 _execute() 会让 Agent 用纯 LLM 模式回答
            return ToolPolicy(required_tool_unavailable=evidence_required)
        if req.tool_call_budget is not None and req.tool_call_budget <= 0:
            return ToolPolicy(required_tool_unavailable=True, skip_execution=True)#上层：跳过执行
        #阶段二：计算白名单
        available = getattr(self, "_available_tool_names", None)
        allowed = tuple(
            name for name in self._AGENT_TOOLS.get(agent_type, ())
            if available is None or name in available
        )
        #GENERAL Agent 只有在意图是 QUERY/REQUEST/MANUAL_REVIEW 时才给工具，否则 allowed = ()——防止通用 Agent 滥用工具。
        if agent_type == AgentType.GENERAL and req.intent not in {
            IntentCategory.QUERY,
            IntentCategory.REQUEST,
            IntentCategory.MANUAL_REVIEW,
        }:
            allowed = ()
        #阶段三：构建参数
        inputs = req.tool_inputs or {}# API已校验的显示业务参数
        message = (req.message or "").lower()
        current = max(1, min(int(inputs.get("current") or 1), 100))
        model_id = inputs.get("model_id")
        package_id = inputs.get("package_id")
        order_id = inputs.get("order_id")
        explicit_keyword = str(inputs.get("model_keyword") or "").strip()
        keyword = explicit_keyword
        if not keyword:
            entity_models = req.entities.get("model", []) if req.entities else []
            if entity_models:
                keyword = str(entity_models[0]).strip()
        defaults: Dict[str, Dict[str, Any]] = {           #默认值，LLM 没填才补
            "knowledge_search": {"query": req.message[:2000], "top_k": 3},
        }
        locked_inputs: Dict[str, Dict[str, Any]] = {            #锁定值，强制覆盖 LLM 生成的值
            "modelhub_hot_models": {"current": current},        #分页参数锁定
            "modelhub_hot_packages": {"current": current},
        }
        category = str(inputs.get("category") or "").strip()
        if category:
            locked_inputs["modelhub_hot_models"]["category"] = category
        if keyword:
            defaults["modelhub_search_models"] = {"keyword": keyword}
            locked_inputs["modelhub_search_models"] = {"current": current}
            if explicit_keyword:
                locked_inputs["modelhub_search_models"]["keyword"] = explicit_keyword
        if model_id is not None:
            locked_inputs["modelhub_get_model"] = {"model_id": int(model_id)}
            locked_inputs["modelhub_list_packages"] = {"model_id": int(model_id)}
            locked_inputs["modelhub_estimate_cost"] = {"model_id": int(model_id)}
        if package_id is not None:
            locked_inputs["modelhub_get_package"] = {"package_id": int(package_id)}
        #阶段四：决定首选工具 first_choice
        first_choice = "auto"
        if agent_type == AgentType.MODEL_ADVISOR:
            if model_id is not None:
                first_choice = "modelhub_get_model"#已知 ID，直接查详情
            elif keyword:
                first_choice = "modelhub_search_models"#有关键词，搜索模型
            elif req.intent == IntentCategory.MODEL_SEARCH:
                first_choice = "modelhub_hot_models"#泛意图，看热门
        elif agent_type == AgentType.COST_OPTIMIZER:
            if model_id is not None:
                first_choice = "modelhub_get_model"
            elif keyword:
                first_choice = "modelhub_search_models"
            elif req.intent == IntentCategory.COST_ESTIMATION:
                first_choice = "modelhub_hot_models"
            elif req.intent == IntentCategory.USAGE_ANALYSIS:
                first_choice = (
                    "auto"
                    if any(record.authoritative for record in req.prefetched_tool_records)# USAGE_ANALYSIS + 有预取权威数据 → "auto"
                    else "knowledge_search"#USAGE_ANALYSIS + 无预取数据 → "knowledge_search"
                )
        elif agent_type == AgentType.QUOTA_ORDER:
            if package_id is not None:
                first_choice = "modelhub_get_package"
            elif model_id is not None and any(kw in message for kw in ["套餐", "库存", "购买", "抢购", "秒杀"]):
                first_choice = "modelhub_list_packages"
            elif order_id is not None:
                first_choice = (
                    "auto"#有 order_id + 有预取数据 → "auto"
                    if any(record.authoritative for record in req.prefetched_tool_records)
                    else "knowledge_search"#有 order_id + 无预取数据 → "knowledge_search"
                )
            elif any(kw in message for kw in ["当前", "现在", "库存", "在售", "价格", "热门套餐", "有哪些套餐"]):
                first_choice = "modelhub_hot_packages"
            elif any(kw in message for kw in ["为什么", "规则", "限制", "抢不到", "有效期", "超时取消"]):
                first_choice = "knowledge_search"
            elif not any(record.authoritative for record in req.prefetched_tool_records):
                first_choice = "any"
        elif agent_type == AgentType.API_SUPPORT:
            if model_id is not None:
                first_choice = "modelhub_get_model"
            elif keyword:
                first_choice = "modelhub_search_models"
            else:
                first_choice = "knowledge_search"
        elif agent_type in {AgentType.QUOTA_RISK, AgentType.MANUAL_REVIEW}:
            first_choice = "knowledge_search"
        #阶段五：组装 ToolPolicy
        required_tool_unavailable = (
            (first_choice == "any" and not allowed)
            or (first_choice not in {"auto", "any"} and first_choice not in allowed)
        )
        if not allowed and first_choice == "auto":# 无工具 + 非强制 → 返回空策略（纯 LLM 模式）
            return ToolPolicy()

        return ToolPolicy(
            allowed_tools=allowed,
            first_choice=first_choice,
            tool_defaults=defaults,
            locked_inputs=locked_inputs,
            max_rounds=getattr(self, "_tool_max_rounds", 3),
            max_calls=(              # 最大调用次数（优先用分片预算）
                req.tool_call_budget # 有分片预算？用分片
                if req.tool_call_budget is not None
                else getattr(self, "_tool_max_calls", 4) # 否则用全局默认值
            ),
            max_parallel_calls=getattr(self, "_tool_max_parallel_calls", 3),
            max_result_chars=getattr(self, "_tool_result_max_chars", 8000),
            required_tool_unavailable=required_tool_unavailable,
        )

    def _best_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        """
        性能路由：从同类 Agent 中选 routing_score() 最高的。
        这是"基于在线表现动态调整路由"的核心。
        """
        agents = self._pool.get(agent_type, [])
        if not agents:
            return None
        #从 agents 列表中找出"最大"的元素
        #lambda a: 匿名函数，参数 a 代表列表中的每个 Agent
        return max(agents, key=lambda a: a.stats.routing_score())

    async def _execute(self, req: Request, agent_type: AgentType) -> AgentResponse:
        """执行 Agent；required evidence 失败关闭，只有 optional 失败可降级到 GeneralAgent。"""
        skill_names = self._skill_names_for_execution(req, agent_type)
        #根据当前 Agent 需要的 skill 名称，从 ProjectSkillRegistry 中查找并读取对应 SKILL.md，返回成功加载的 skill 名和 skill 指令内容
        resolved_names, instructions = self._skill_registry.resolve(skill_names)
        # run_parallel 会共享原 Request；每个协作者必须使用独立副本，避免 Skill 串写。
        #基于原来的 req 创建一个新的 Request 对象，只把 skill_instructions 字段替换成新的 instructions，其他字段保持不变。
        policy = self._tool_policy_for_execution(req, agent_type)
        agent_req = replace(req, skill_instructions=instructions, tool_policy=policy)

        if policy.required_tool_unavailable:
            return AgentResponse(
                agent_type=agent_type,
                content=(
                    "当前所需的权威查询工具未启用或本次工具预算不足，因此不能核验实时价格、库存、订单、余额或平台规则。"
                    "请稍后重试或联系平台确认。"
                ),
                success=not policy.skip_execution,
                review_required=agent_type in {AgentType.QUOTA_RISK, AgentType.MANUAL_REVIEW},
                skills_used=resolved_names,
            )

        agent = self._best_agent(agent_type)
        if agent is None:
            agent = self._best_agent(AgentType.GENERAL)
        if agent is None:
            return AgentResponse(
                agent_type=AgentType.GENERAL,
                content="服务暂时不可用，请稍后重试。",
                success=False,
            )

        response = await agent.handle(agent_req)

        required_tool_failed = (
            not response.success
            and bool(policy.allowed_tools)
            and policy.first_choice != "auto"
        )
        if required_tool_failed:
            # Required evidence cannot be replaced by an unconstrained no-tool answer.
            response.content = (
                "当前无法调用本问题所需的权威查询工具，因此不能核验实时价格、库存、订单、余额或平台规则。"
                "请稍后重试；涉及交易、账号或风控结论时请提交平台侧确认。"
            )
            response.success = True
            response.review_required = agent_type in {AgentType.QUOTA_RISK, AgentType.MANUAL_REVIEW}

        # 专属 Agent 失败时降级到 GeneralAgent
        if not response.success and agent_type != AgentType.GENERAL:
            logger.warning(f"{agent_type.value} 失败，降级到 GeneralAgent")
            fallback = self._best_agent(AgentType.GENERAL)
            if fallback:
                # A gateway/tool failure must still be able to fall back to a plain LLM response.
                degraded_context = "\n\n".join(part for part in [
                    agent_req.context,
                    "[系统降级状态] 本轮实时/知识工具不可用。不得声称已核验当前价格、库存、订单、余额或平台规则；必要时请用户稍后重试。",
                ] if part)
                response = await fallback.handle(replace(
                    agent_req,
                    context=degraded_context,
                    tool_policy=ToolPolicy(),
                ))

        response.skills_used = resolved_names

        return response

    # ── 统计（供 Monitor 读取）────────────────────────────────────────────────
    #返回所有 Agent 的调用次数、成功率、平均耗时、惩罚值和路由分数。
    def get_stats(self) -> Dict[str, Any]:
        result = {}
        for agent_type, agents in self._pool.items():
            for i, agent in enumerate(agents):
                key = f"{agent_type.value}_{i}"
                result[key] = {
                    "total":        agent.stats.total,#调用次数
                    "success_rate": round(agent.stats.success_rate, 3),#成功率
                    "avg_ms":       round(agent.stats.avg_ms, 1),#平均耗时
                    "monitor_penalty": round(agent.stats.monitor_penalty, 3),#监控模块的惩罚值 保留 3 位小数后放进返回结果里。
                    "routing_score": round(agent.stats.routing_score(), 3),#路由分数
                }
        return result
    #接收监控模块传来的惩罚配置。
    def update_routing_penalties(self, penalties: Dict[str, float]) -> None:
        """
        接收 Monitor 的在线表现反馈，动态调整路由惩罚项。

        penalties 的 key 使用 get_stats() 中的 agent key，例如 local_guide_0。
        """
        #遍历 Agent 池，根据 key 更新每个 Agent 的 monitor_penalty，并限制在 0.0 到 0.9 之间。
        for agent_type, agents in self._pool.items():
            for i, agent in enumerate(agents):
                key = f"{agent_type.value}_{i}"
                penalty = penalties.get(key, 0.0)#根据 key 取对应的惩罚值。
                agent.stats.monitor_penalty = min(max(penalty, 0.0), 0.9)
