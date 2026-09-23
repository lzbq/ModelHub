"""
亮点：端到端意图识别
把用户的一句话识别成一个业务意图，同时给出置信度、紧急程度、实体信息和耗时。
它会被 AgentOrchestrator 调用，用来决定后面交给模型选型、成本、套餐订单、API 支持或风控 Agent。
整体流程：
用户消息
  -> 查缓存
  -> LLM 意图识别
  -> Embedding 相似度识别
  -> 关键词匹配
  -> 三路加权投票
  -> 提取实体
  -> 判断紧急程度
  -> 返回 IntentResult

三路融合策略：
  1. LLM 语义理解（权重 70%）—— 主力，理解复杂语义和上下文
  2. 中文 Embedding 向量相似度（权重 20%）—— 快速匹配常见表达
  3. 关键词模式匹配（权重 10%）—— 零延迟兜底

三路结果通过加权投票合并，置信度低于阈值时降级为 OTHER。
LLM 和 Embedding 并行调用，不串行等待。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from storage.vector_store import TextEmbedder

logger = logging.getLogger(__name__)


class IntentCategory(Enum):
    QUERY      = "query"       # 查询信息
    COMPLAINT  = "complaint"   # 投诉不满
    REQUEST    = "request"     # 请求操作
    GREETING   = "greeting"    # 问候
    MANUAL_REVIEW = "manual_review"  # 需平台侧确认/人工审核
    FEEDBACK   = "feedback"    # 正面反馈
    MODEL_SEARCH = "model_search"          # 模型查找、比较与选型
    COST_ESTIMATION = "cost_estimation"    # Token 用量与成本估算
    TOKEN_PACKAGE = "token_package"        # 套餐、秒杀、订单与额度
    API_SUPPORT = "api_support"            # API/SDK/错误码支持
    USAGE_ANALYSIS = "usage_analysis"      # 额度消耗与异常趋势分析
    RISK       = "risk"                    # 刷购、Key 共享、异常调用
    OTHER      = "other"

#紧急程度
class UrgencyLevel(Enum):
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4


@dataclass
class IntentResult:
    intent:     IntentCategory
    confidence: float #置信度，表示模型有多确定。
    urgency:    UrgencyLevel #紧急程度
    entities:   Dict[str, List[str]]   # 从消息中提取的实体
    reasoning:  str #LLM 给出的一句话判断理由。
    latency_ms: float #本次识别耗时，单位毫秒。


# ── Few-shot 模板（同时用于 LLM 示例和 Embedding 匹配）────────────────────────
#1.给 LLM 当示例，让它知道每种意图长什么样。
#2.给 Embedding 匹配用，把用户消息和模板句子做相似度比较。
_TEMPLATES: Dict[IntentCategory, List[str]] = {
    IntentCategory.QUERY:      ["我的订单状态是什么？", "如何重置密码？", "快递什么时候到？"],
    IntentCategory.COMPLAINT:  ["等了好几个小时！", "服务太差了！", "一直没人处理！"],
    IntentCategory.REQUEST:    ["帮我取消订单", "我需要修改地址", "请协助退款"],
    IntentCategory.GREETING:   ["你好", "嗨，有人吗", "早上好"],
    IntentCategory.MANUAL_REVIEW: ["我要投诉，需要平台侧确认！", "这个问题需要人工审核吗？", "请平台复核一下"],
    IntentCategory.FEEDBACK:   ["服务很棒！", "非常满意", "给个好评"],
    IntentCategory.MODEL_SEARCH: ["适合中文知识库的模型有哪些？", "帮我比较推理模型和通用模型", "目前有哪些热门模型？"],
    IntentCategory.COST_ESTIMATION: ["每天一万次问答一个月要多少 Token？", "帮我估算这个应用的模型成本", "预算一千元怎么选模型？"],
    IntentCategory.TOKEN_PACKAGE: ["限时 Token 套餐为什么抢不到？", "这个模型有哪些 Token 套餐？", "支付后额度为什么没到账？"],
    IntentCategory.API_SUPPORT: ["API Key 怎么配置？", "429 错误是什么意思？", "给我一个 Python SDK 调用示例"],
    IntentCategory.USAGE_ANALYSIS: ["最近 Token 为什么消耗这么快？", "帮我分析额度使用趋势", "我的剩余额度是多少？"],
    IntentCategory.RISK:       ["是否存在批量刷套餐？", "API Key 共享有什么风险？", "调用量突然暴增正常吗？"],
}

# 紧急关键词
_URGENCY_KEYWORDS = {
    UrgencyLevel.CRITICAL: ["紧急", "emergency", "urgent", "asap", "立刻"],
    UrgencyLevel.HIGH:     ["今天", "马上", "尽快", "hurry", "now"],
    UrgencyLevel.MEDIUM:   ["这周", "soon", "快点"],
}


def _cosine(a: List[float], b: List[float]) -> float:
    """纯 Python 余弦相似度，不依赖 numpy。"""
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class IntentRecognizer:
    """
    端到端意图识别器。

    LLM 识别通过 Anthropic 兼容接口调用；模板相似度识别复用项目统一的 TextEmbedder。
    模板 Embedding 在首次请求时懒加载并缓存，后续复用。
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.5,
        embedding_backend: str = "stable",
        embedding_model: str = "",
        embedding_dim: int = 256,
        query_instruction: str = "",
        embedding_device: str = "",
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client    = AsyncAnthropic(**kwargs)
        self.model     = model
        self.threshold = confidence_threshold #保存投票结果最低置信度阈值，默认是 0.5。

        self._embedder: Optional[TextEmbedder] = None
        try:
            self._embedder = TextEmbedder(
                backend=embedding_backend,
                dim=embedding_dim,
                model_name=embedding_model,
                query_instruction=query_instruction,
                device=embedding_device,
            )
            self._embedding_enabled = True
            logger.info(f"意图识别 Embedding: {embedding_backend} {embedding_model or '(stable hash)'} dim={embedding_dim}")
        except Exception as ex:
            self._embedding_enabled = False
            logger.warning(f"意图识别 Embedding 初始化失败，将只使用 LLM + 关键词: {ex}")

        self._tpl_embeddings: Dict[IntentCategory, List[List[float]]] = {}#保存模板向量
        self._cache: Dict[str, IntentResult] = {}#保存识别结果缓存
        self.cache_hits   = 0
        self.cache_misses = 0

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    async def recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentResult:
        """
        识别用户意图。

        history 格式：[{"role": "user"/"assistant", "content": "..."}]
        """
        key = self._cache_key(message)#生成缓存 key
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        self.cache_misses += 1

        t0 = time.monotonic()

        # LLM 和 Embedding 并行（Embedding 不可用时跳过）
        llm_task = asyncio.create_task(self._llm_recognize(message, history))
        emb_task = asyncio.create_task(self._embedding_recognize(message)) if self._embedding_enabled else None
        pat      = self._pattern_recognize(message)

        if emb_task:
            llm, emb = await asyncio.gather(llm_task, emb_task)
        else:
            llm = await llm_task
            emb = {"intent": IntentCategory.OTHER, "confidence": 0.0}

        intent = self._vote(llm, emb, pat)
        entities = await self._extract_entities(message)
        urgency  = self._urgency(message, intent)

        result = IntentResult(
            intent=intent,
            confidence=llm["confidence"],
            urgency=urgency,
            entities=entities,
            reasoning=llm.get("reasoning", ""),
            latency_ms=(time.monotonic() - t0) * 1000,
        )

        # LRU 缓存
        if len(self._cache) >= 1000:
            for k in list(self._cache)[:500]:
                del self._cache[k]
        self._cache[key] = result
        return result
    #这个方法用于手动纠正意图。
    def learn(self, message: str, correct: IntentCategory) -> None:
        """在线学习：将纠正样本加入模板，清除对应 Embedding 缓存。"""
        #字典的 setdefault() 方法：先拿到正确意图对应的模板列表；如果还没有这个意图的模板列表，就创建一个空列表。
        tpls = _TEMPLATES.setdefault(correct, [])
        if message not in tpls:
            tpls.append(message)#会把这句话加入对应模板
            self._tpl_embeddings.pop(correct, None)  # 删除该意图的 embedding 缓存,下次会重新计算模板向量。因为模板变了，向量也要重新算
            logger.info(f"学习新样本 → {correct.value}: {message[:40]}")

    # ── 三路识别策略 ──────────────────────────────────────────────────────────

    async def _llm_recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """策略 1：LLM 语义理解（Few-shot + 上下文）。"""
        message = self._clean_text(message)
        # 构建 Few-shot 示例
        examples = "\n".join(
            f'  消息: "{t}" → 意图: {cat.value}'
            for cat, tpls in _TEMPLATES.items()
            for t in tpls[:1]  # 每类取 1 条，控制 prompt 长度
        )#生成器表达式，可以理解为“边循环边生成字符串”。
        # 最近 3 轮对话上下文
        ctx = ""
        if history:
            ctx = "\n最近对话:\n" + "\n".join(
                f"  {self._clean_text(m.get('role', 'user'))}: {self._clean_text(m.get('content', ''))}"
                for m in history[-3:]
            )

        prompt = f"""你是大模型 API 服务平台的意图分析专家。根据示例判断用户意图，返回 JSON。

判定优先级：当问题明确涉及 Token 套餐、库存、抢购、支付、订单或额度时，即使用户带有不满语气，也优先归类为 token_package；只有缺少明确业务对象、主要表达服务不满时才归类为 complaint。

示例:
{examples}

{ctx}
用户消息: "{message}"

返回格式（仅 JSON，不要其他文字）:
{{"intent": "<意图值>", "confidence": <0-1>, "reasoning": "<一句话说明>"}}

可选意图: {", ".join(c.value for c in IntentCategory)}"""
        prompt = self._clean_text(prompt)

        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            try:
                data["intent"] = IntentCategory(data["intent"])#把字符串意图转成枚举
            except ValueError:
                #如果 LLM 返回了一个不存在的意图，就兜底成：
                data["intent"] = IntentCategory.OTHER
            return data
        except Exception as ex:
            logger.warning(f"LLM 识别失败: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0, "reasoning": "LLM 失败", "failed": True}

    async def _embedding_recognize(self, message: str) -> Dict[str, Any]:
        """策略 2：Embedding 向量相似度匹配。
        把用户消息向量化，然后和模板句子向量比较相似度。
        """
        try:
            await self._load_template_embeddings()#先加载所有模板的向量。
            msg_vec = await self._embed_text(message)#把用户消息转成向量。

            best_cat, best_score = IntentCategory.OTHER, 0.0
            for cat, vecs in self._tpl_embeddings.items():
                score = max(_cosine(msg_vec, v) for v in vecs)
                if score > best_score:
                    best_score, best_cat = score, cat

            return {"intent": best_cat, "confidence": best_score}
        except Exception as ex:
            logger.warning(f"Embedding 识别失败: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0}

    def _pattern_recognize(self, message: str) -> Dict[str, Any]:
        """策略 3：关键词模式匹配（同步，零延迟兜底）。"""
        msg = message.lower()
        patterns = {
            IntentCategory.MODEL_SEARCH: ["模型", "选型", "推荐", "比较", "上下文", "推理", "embedding", "图像生成", "热门模型"],
            IntentCategory.COST_ESTIMATION: ["成本", "预算", "估算", "多少钱", "费用", "token 数", "调用量"],
            IntentCategory.TOKEN_PACKAGE: ["套餐", "额度", "秒杀", "抢购", "订单", "支付", "到账", "库存", "有效期"],
            IntentCategory.API_SUPPORT: ["api key", "apikey", "sdk", "接口", "错误码", "429", "401", "限流", "请求格式"],
            IntentCategory.USAGE_ANALYSIS: ["用量", "消耗", "额度消耗", "消耗很快", "余额", "剩余", "趋势", "账单", "调用统计"],
            IntentCategory.RISK:       ["刷购", "共享 key", "key 共享", "异常调用", "风控", "批量账号", "盗用", "被盗用", "key 被盗"],
            IntentCategory.MANUAL_REVIEW: ["投诉", "人工审核", "平台确认", "平台侧确认", "复核", "申诉"],
            IntentCategory.COMPLAINT:  ["太差", "糟糕", "horrible", "等了很久"],
            IntentCategory.GREETING:   ["你好", "嗨", "hello", "hi"],
            IntentCategory.REQUEST:    ["请帮我", "麻烦帮我", "需要你", "please", "help"],
            IntentCategory.QUERY:      ["?", "？", "怎么", "什么", "status"],
        }
        best_cat, best_score = IntentCategory.OTHER, 0.0
        for cat, kws in patterns.items():
            hits = sum(1 for kw in kws if kw in msg)#遍历每类关键词，统计命中数
            if hits:
                business_boost = 1.0 if cat in {
                    IntentCategory.MODEL_SEARCH,
                    IntentCategory.COST_ESTIMATION,
                    IntentCategory.TOKEN_PACKAGE,
                    IntentCategory.API_SUPPORT,
                    IntentCategory.USAGE_ANALYSIS,
                    IntentCategory.RISK,
                } else 0.0
                score = hits + business_boost
                if score > best_score:
                    best_score, best_cat = score, cat
        return {"intent": best_cat, "confidence": min(1.0, best_score / 2.0)}

    # ── 投票合并 ──────────────────────────────────────────────────────────────

    def _vote(self, llm: Dict, emb: Dict, pat: Dict) -> IntentCategory:
        """加权投票。如果 LLM 失败，就优先用 embedding，embedding 不行再用关键词，最后返回 OTHER。"""
        if llm.get("failed"):
            if emb.get("intent") != IntentCategory.OTHER and emb.get("confidence", 0.0) > 0:
                return emb["intent"]
            if pat.get("intent") != IntentCategory.OTHER and pat.get("confidence", 0.0) > 0:
                return pat["intent"]
            return IntentCategory.OTHER
        #如果 LLM 正常，并且 embedding 可用
        if self._embedding_enabled:
            weights = [(llm, 0.7), (emb, 0.2), (pat, 0.1)]
        else:#如果 embedding 不可用：
            weights = [(llm, 0.85), (pat, 0.15)]
        scores: Dict[IntentCategory, float] = {}
        for result, w in weights:
            cat  = result.get("intent", IntentCategory.OTHER)
            conf = result.get("confidence", 0.0)
            #从 scores 里取出当前意图已有的分数；如果还没有，就用 0.0
            scores[cat] = scores.get(cat, 0.0) + w * conf
        #从 scores 字典的所有 key 里面，找出 value 最大的那个 key。
        best = max(scores, key=scores.get)  # type: ignore 选最高分
        return best if scores[best] >= self.threshold else IntentCategory.OTHER #threshold：阈值

    # ── 实体提取 ──────────────────────────────────────────────────────────────

    async def _extract_entities(self, message: str) -> Dict[str, List[str]]:
        """用 LLM 从消息中提取结构化实体。"""
        message = self._clean_text(message)
        prompt = f"""从大模型服务咨询中提取实体，返回 JSON（字段值为列表，没有则为空列表）:
消息: "{message}"
格式: {{"order_id":[],"model":[],"provider":[],"package":[],"token_amount":[],"budget":[],"error_code":[]}}"""
        prompt = self._clean_text(prompt)
        try:
            resp = await self.client.messages.create(
                model=self.model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            return json.loads(raw[s:e])
        except Exception:
            return {"order_id": [], "model": [], "provider": [], "package": [], "token_amount": [], "budget": [], "error_code": []}

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    async def _load_template_embeddings(self) -> None:
        """懒加载所有模板的 Embedding（只在首次调用时执行）。"""
        missing = [cat for cat in _TEMPLATES if cat not in self._tpl_embeddings]#找出还没有向量缓存的意图。
        if not missing:
            return
        #把这些模板句子摊平成一个列表。
        all_texts = [t for cat in missing for t in _TEMPLATES[cat]]
        vecs = [await self._embed_text(text, is_query=False) for text in all_texts]#逐个生成向量
        idx = 0
        #然后再按意图分组存回
        for cat in missing:
            n = len(_TEMPLATES[cat])
            self._tpl_embeddings[cat] = vecs[idx: idx + n]
            idx += n

    async def _embed_text(self, text: str, *, is_query: bool = True) -> List[float]:
        """使用统一 TextEmbedder 生成文本向量。"""
        if self._embedder is None:
            raise RuntimeError("意图识别 Embedding 未初始化")
        return await asyncio.to_thread(self._embedder.embed, text, is_query=is_query)

    #紧急程度
    def _urgency(self, message: str, intent: IntentCategory) -> UrgencyLevel:
        msg = message.lower()
        #先查关键词
        for level, kws in _URGENCY_KEYWORDS.items():
            if any(kw in msg for kw in kws):
                return level
        #如果没有命中关键词，再根据意图兜底
        if intent == IntentCategory.MANUAL_REVIEW:
            return UrgencyLevel.CRITICAL
        if intent == IntentCategory.COMPLAINT:
            return UrgencyLevel.HIGH
        #其他默认：
        return UrgencyLevel.LOW

    def _cache_key(self, message: str) -> str:
        return self._clean_text(message)[:200]

    @staticmethod
    def _clean_text(value: Any) -> str:
        """移除 Unicode 代理字符，避免 HTTP 客户端编码 prompt 时崩溃。"""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")
    #返回缓存状态
    @property
    def cache_stats(self) -> Dict[str, Any]:
        total = self.cache_hits + self.cache_misses
        return {
            "size": len(self._cache),
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": self.cache_hits / total if total else 0.0,
        }
