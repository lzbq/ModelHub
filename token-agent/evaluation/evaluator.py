"""
亮点：端到端 Agent 评测框架

流程：
POST /eval/run
  -> _evaluator.run()
  -> 跑意图识别测试--计算 accuracy 和 macro_f1
  -> 跑对话质量测试--完整 /chat 主链路，生成真实 Agent 回复-> 做关键门禁与诊断覆盖校验-> LLM-as-Judge 打分（相关性、准确性、完整性、有用性）
  -> 汇总对话质量平均分；pass_rate 只统计对话主评测，意图识别放入 diagnostic_scores
  -> 把当前分数和上一次评测或 baseline 比较(如果某个指标下降超过 5%，加入 regressions)
  -> 根据低分指标生成优化建议
  -> 仅在调用方显式请求时保存当前结果为新的 baseline，并返回报告。

核心问题：如何评测端到端 Agent？
评测维度：
  1. 意图识别准确率 —— 预测意图 vs 标注意图，计算 Accuracy / F1
  2. 规则校验 —— 关键门禁检查安全与业务边界，诊断覆盖记录表达、路由和工具链路
  3. 响应质量评分 —— 用 LLM-as-Judge 从相关性、准确性、完整性、有用性四个维度打分
  4. 端到端对话评测 —— 模拟完整多轮对话，评估整体体验
  5. 回归测试 —— 与历史基线对比，防止性能退化

LLM-as-Judge 适合评估表达质量，但不能单独代表业务正确性；
因此本模块会把可程序化判断的业务规则单独校验，Judge 失败也会从质量均分中剔除。
"""
import asyncio
import json
import logging
import pathlib
import re
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.intent_recognizer import IntentCategory, IntentRecognizer

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────────────
#表示一条意图识别测试用例
@dataclass
class IntentTestCase:
    message:          str#用户输入
    expected_intent:  str#期望识别出来的意图
    context:          Optional[Dict[str, Any]] = None#可选上下文

@dataclass
class QualityScores:
    """LLM-as-Judge 评分结果。"""
    relevance:    float   # 相关性：回答是否针对问题
    accuracy:     float   # 准确性：信息是否正确
    completeness: float   # 完整性：是否完整解决问题
    helpfulness:  float   # 有用性：用户是否能据此行动
    judge_failed: bool = False
    error: Optional[str] = None

    @property
    def overall(self) -> float:
        return statistics.mean([self.relevance, self.accuracy, self.completeness, self.helpfulness])

@dataclass
class HardRuleCheck:
    """关键门禁与诊断规则的组合结果。"""
    passed: bool  # 总门禁结果。只有安全/交易边界/实时数据等关键门禁全部通过且没有命中禁忌说法时才为 True。（forbidden_hits 为空且critical_errors 为空）
    score: float  # 非关键规则覆盖率
    critical_score: float = 1.0#关键规则覆盖率
    missing_expected_points: List[str] = field(default_factory=list)#回答里缺少了测试用例要求必须覆盖的要点
    forbidden_hits: List[str] = field(default_factory=list)#回答命中了禁忌说法
    route_errors: List[str] = field(default_factory=list)#路由类错误 例如意图识别不符、Agent类型不符
    usage_errors: List[str] = field(default_factory=list)#工具使用错误。测试用例要求走知识库但没走、要求用某个工具但没用
    critical_errors: List[str] = field(default_factory=list)#关键性错误。人工审核标记不符、实时业务数据未调用、关键工具（critical=True）未使用
    unchecked_required_tools: List[str] = field(default_factory=list)#无法精确追踪的工具。表示测试用例声明了某个必需工具，但当前评测器还不知道如何精确判断它有没有被使用。

    @property
    def summary(self) -> str:
        issues = []
        if self.missing_expected_points:
            issues.append(f"诊断缺少要点: {', '.join(self.missing_expected_points)}")
        if self.forbidden_hits:
            issues.append(f"关键禁忌命中: {', '.join(self.forbidden_hits)}")
        issues.extend(self.critical_errors)
        issues.extend(self.route_errors)
        issues.extend(self.usage_errors)
        if self.unchecked_required_tools:#如果存在无法精确追踪的必需工具，也汇总进去
            issues.append(f"未精确追踪工具: {', '.join(self.unchecked_required_tools)}")
        return "；".join(issues) if issues else "关键门禁通过，诊断规则通过"

@dataclass
class EvalResult:
    """单个测试项结果。"""
    test_id:    str
    passed:     bool
    scores:     Dict[str, float]
    detail:     str = ""
    metadata:   Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    """评测报告。"""
    timestamp:        str
    total:            int                # 主评测测试数，只统计对话质量用例
    passed:           int                # 主评测通过数，只统计对话质量用例
    pass_rate:        float              # 主评测通过率，不包含诊断项
    avg_scores:       Dict[str, float]   # 对话质量平均分和规则指标
    diagnostic_scores: Dict[str, float]  # 诊断指标，例如意图识别准确率和 Macro-F1
    regressions:      List[str]          # 相比基线退化的指标
    recommendations:  List[str]          # 优化建议
    results:          List[EvalResult]   # 每条测试详情


# ── LLM-as-Judge ─────────────────────────────────────────────────────────────

class LLMJudge:
    """
    用 LLM 评判 Agent 响应的表达质量和主观完整度。

    为什么保留 LLM Judge？
    - 可规模化：数千条测试用例自动评测
    - 可重复：相同输入得到稳定评分
    - 多维度：同时评估相关性、准确性等多个维度

    注意：LLM Judge 本身也有偏差，只作为质量评分的一部分；
    业务边界和禁忌说法由关键门禁负责，路由和工具链路作为诊断指标记录。
    """

    JUDGE_PROMPT = """你是一个严格的大模型 API 服务平台 Agent 质量评估专家。请对以下 Agent 响应进行评分。

用户问题: {question}
Agent 响应: {response}
{context_section}
{expectation_section}

评分时请围绕 ModelHub 业务：模型选型、Token 成本、套餐抢购、订单额度、API/SDK 支持和调用风控。
涉及抢购、支付、退款、额度调整和 API Key 操作时，Agent 只能解释规则或引导用户回到业务页面，不能声称已经代替用户执行。
如果提供了必含要点或禁忌说法，请据此从严评分：遗漏关键要点要降低 completeness；出现禁忌说法要显著降低 accuracy。
如果回答编造了未在问题、背景信息或业务规则中出现的模型参数、价格、库存、订单状态或已执行操作，也要降低 accuracy。

请从以下四个维度评分（0.0-1.0），返回 JSON：
- relevance: 响应是否直接针对大模型服务场景下的用户问题（0=完全无关，1=完全相关）
- accuracy: 是否符合模型、Token 计费、订单额度、API 安全和风控规则（0=明显错误，1=完全正确）
- completeness: 是否覆盖用户需要的关键信息、限制条件和下一步（0=完全没解决，1=完整解决）
- helpfulness: 用户或商家能否据此采取下一步行动（0=毫无帮助，1=非常有帮助）

只返回 JSON，例如: {{"relevance": 0.9, "accuracy": 0.8, "completeness": 0.7, "helpfulness": 0.85}}"""

    def __init__(self, client: AsyncAnthropic, model: str):
        self._client = client
        self._model  = model

    async def judge(
        self,
        question: str,
        response: str,
        context: Optional[str] = None,
        expected_points: Optional[List[str]] = None,
        forbidden_claims: Optional[List[str]] = None,
    ) -> QualityScores:
        ctx_section = f"背景信息: {context}" if context else ""
        #传入 expected_points（必含要点）和 forbidden_claims（禁忌说法），让 Judge 从严评分
        expectation_section = self._expectation_section(expected_points, forbidden_claims)
        prompt = self.JUDGE_PROMPT.format(#把 JUDGE_PROMPT 里的占位符替换掉
            question=question,
            response=response,
            context_section=ctx_section,
            expectation_section=expectation_section,
        )
        prompt = self._clean_text(prompt)
        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            return QualityScores(
                relevance=float(data.get("relevance", 0.5)),
                accuracy=float(data.get("accuracy", 0.5)),
                completeness=float(data.get("completeness", 0.5)),
                helpfulness=float(data.get("helpfulness", 0.5)),
            )
        except Exception as ex:
            logger.warning(f"LLM Judge 失败: {ex}")
            return QualityScores(
                0.0, 0.0, 0.0, 0.0,
                judge_failed=True,
                error=str(ex),
            )

    @staticmethod
    def _expectation_section(
        expected_points: Optional[List[str]],
        forbidden_claims: Optional[List[str]],
    ) -> str:
        parts = []
        if expected_points:
            parts.append("必含要点:\n" + "\n".join(f"- {p}" for p in expected_points))
        if forbidden_claims:
            parts.append("禁忌说法:\n" + "\n".join(f"- {p}" for p in forbidden_claims))
        return "\n".join(parts)

    @staticmethod
    def _clean_text(value: Any) -> str:
        """移除 Unicode 代理字符，避免 LLM 请求编码失败。"""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")


# ── 意图识别评测 ──────────────────────────────────────────────────────────────

class IntentEvaluator:
    """评测意图识别的准确率和 F1。"""

    def __init__(self, recognizer: IntentRecognizer):
        self._recognizer = recognizer

    async def evaluate(self, cases: List[IntentTestCase]) -> Dict[str, Any]:
        predictions, ground_truth = [], []
        case_details: List[Dict[str, Any]] = []

        for case in cases:
            result = await self._recognizer.recognize(case.message)#意图识别结果 IntentResult
            predicted = result.intent.value
            predictions.append(predicted)
            ground_truth.append(case.expected_intent)
            case_details.append({
                "message": case.message,
                "expected": case.expected_intent,# 期望的意图
                "predicted": predicted,          # 预测的意图
                "confidence": result.confidence, # 意图的置信度
                "reasoning": result.reasoning,   # 意图的推理
            })

        # 纯 Python 计算指标
        correct = sum(p == g for p, g in zip(predictions, ground_truth))
        accuracy = correct / len(predictions) if predictions else 0.0

        # 每类 F1
        labels = sorted(set(ground_truth + predictions))# 合并真实标签和预测标签，去重后排序，得到所有出现过的意图类别
        per_class: Dict[str, Dict[str, float]] = {}
        for label in labels:
            tp = sum(p == label and g == label for p, g in zip(predictions, ground_truth))
            fp = sum(p == label and g != label for p, g in zip(predictions, ground_truth))
            fn = sum(p != label and g == label for p, g in zip(predictions, ground_truth))
            prec = tp / (tp + fp) if (tp + fp) else 0.0# 精确率
            rec  = tp / (tp + fn) if (tp + fn) else 0.0# 召回率
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0  # F1
            per_class[label] = {"precision": prec, "recall": rec, "f1": f1}
        #计算所有意图类别 F1 分数的平均值
        macro_f1 = statistics.mean(v["f1"] for v in per_class.values()) if per_class else 0.0

        return {
            "accuracy":   round(accuracy, 4),# 准确率
            "macro_f1":   round(macro_f1, 4),# 所有意图类别平均 F1
            "per_class":  per_class, # per_class = {"model_advisor": {"precision": 0.9, "recall": 0.85, "f1": 0.874}, ...}

            "total":      len(cases),        # 总测试用例数
            "correct":    correct,           # 正确预测的个数
            "cases":      case_details,      # 测试用例详情
        }


# ── 端到端评测器 ──────────────────────────────────────────────────────────────

class EndToEndEvaluator:
    """
    端到端 Agent 评测。

    评测流程：
      1. 运行意图识别评测（准确率/F1）
      2. 运行对话质量评测（完整 /chat 链路 + 关键门禁/诊断规则 + LLM-as-Judge）
      3. 与历史基线对比（回归检测）
      4. 生成可操作的优化建议
    """

    # 质量及格线
    PASS_THRESHOLD = 0.75
    RULE_COVERAGE_THRESHOLD = 0.80

    def __init__(
        self,
        orchestrator,
        recognizer: IntentRecognizer,
        api_key:  str,
        base_url: Optional[str] = None,
        model:    str = "claude-3-5-sonnet-20241022",
        baseline_path: Optional[str] = None, #基线路径 是一个用于保存和加载评测基线结果的文件路径。
        chat_runner: Optional[Callable[[str, str, str, Dict[str, Any], int], Awaitable[Dict[str, Any]]]] = None,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncAnthropic(**kwargs)

        self._orchestrator     = orchestrator
        self._judge            = LLMJudge(client, model)
        self._intent_evaluator = IntentEvaluator(recognizer)
        self._chat_runner      = chat_runner
        self._history:         List[EvalReport] = []
        self._baseline_path = pathlib.Path(baseline_path) if baseline_path else None #转换为 Path 对象
        self._baseline: Optional[EvalReport] = self._load_baseline() #加载历史基线数据

    async def run(
        self,
        intent_cases:    Optional[List[IntentTestCase]] = None,
        dialog_cases:    Optional[List[Dict[str, Any]]] = None,
        *,
        update_baseline: bool = False,
    ) -> EvalReport:
        """
        运行完整评测。

        intent_cases: 意图识别测试用例
        dialog_cases:
          - 单轮: [{"question": "..."}]
          - 多轮: [{"turns": ["第一轮", "第二轮", ...]}]
        """
        results: List[EvalResult] = []
        all_scores: Dict[str, List[float]] = {
            "relevance": [], "accuracy": [], "completeness": [], "helpfulness": [],
            "rule_score": [], "critical_rule_score": []
        }# 用于保存 Judge 指标、诊断覆盖分和关键门禁分。Judge 失败的样本不进入四个主观质量均分。
        diagnostic_scores: Dict[str, float] = {}
        dialog_total = 0
        judge_failed_count = 0
        critical_rule_passed_count = 0
        run_namespace = f"eval_{uuid.uuid4().hex}"

        # 1. 意图识别评测
        intent_metrics: Dict[str, Any] = {}
        if intent_cases:
            intent_metrics = await self._intent_evaluator.evaluate(intent_cases)
            diagnostic_scores["intent_accuracy"] = intent_metrics["accuracy"]
            diagnostic_scores["intent_macro_f1"] = intent_metrics["macro_f1"]
            results.append(EvalResult(
                test_id="intent_recognition",
                passed=intent_metrics["accuracy"] >= self.PASS_THRESHOLD,
                scores={"accuracy": intent_metrics["accuracy"], "macro_f1": intent_metrics["macro_f1"]},
                detail=f"诊断项：准确率 {intent_metrics['accuracy']:.1%}，Macro-F1 {intent_metrics['macro_f1']:.3f}，不参与 pass_rate",
                metadata={
                    "result_type": "diagnostic",
                    "participates_in_pass_rate": False, #不参与 pass_rate
                    "total": intent_metrics.get("total", 0),
                    "correct": intent_metrics.get("correct", 0),
                    "cases": intent_metrics.get("cases", []),
                },
            ))

        # 2. 对话质量评测。优先走完整 /chat 主链路；再做关键门禁、诊断规则和 LLM Judge 评分。
        if dialog_cases:
            for i, case in enumerate(dialog_cases):
                case_results = await self._evaluate_dialog_case(
                    case,
                    i,
                    run_namespace=run_namespace,#跨 run 使用随机 UUID 隔离
                )#调用 Orchestrator 生成回复，然后用 LLMJudge 给回复打分
                results.extend(case_results)#将当前用例的评测结果添加到总结果列表。extend 是因为 case_results 是一个列表（可能有多轮对话）
                for r in case_results:
                    dialog_total += 1
                    if r.metadata.get("judge_failed"):
                        judge_failed_count += 1
                    if r.metadata.get("critical_rule_passed", True):
                        critical_rule_passed_count += 1
                    for k in all_scores:#遍历质量指标和规则分。
                        if k in {"rule_score", "critical_rule_score"} and k in r.scores:
                            all_scores[k].append(r.scores[k])
                        elif k in r.scores and not r.metadata.get("judge_failed"):
                            all_scores[k].append(r.scores[k])

        # 3. 汇总
        avg_scores = {
            k: round(statistics.mean(v), 4) for k, v in all_scores.items() if v
        }
        if dialog_total:
            avg_scores["judge_failed_rate"] = round(judge_failed_count / dialog_total, 4)
            critical_pass_rate = round(critical_rule_passed_count / dialog_total, 4)
            avg_scores["critical_rule_pass_rate"] = critical_pass_rate

        primary_results = [
            r for r in results
            if r.metadata.get("participates_in_pass_rate", True)
        ]
        passed_count = sum(1 for r in primary_results if r.passed)
        pass_rate    = passed_count / len(primary_results) if primary_results else 0.0

        # 4. 回归检测--与历史基线对比
        regressions = self._detect_regressions({**avg_scores, **diagnostic_scores})

        # 5. 优化建议
        recommendations = self._recommendations(avg_scores, diagnostic_scores)

        report = EvalReport(
            timestamp=datetime.now().isoformat(),
            total=len(primary_results),
            passed=passed_count,
            pass_rate=round(pass_rate, 4),
            avg_scores=avg_scores,
            diagnostic_scores=diagnostic_scores,
            regressions=regressions,
            recommendations=recommendations,
            results=results,
        )
        self._history.append(report)
        if update_baseline:
            self._save_baseline(report)
        return report

    async def _evaluate_dialog_case(
        self,
        case: Dict[str, Any],
        case_idx: int,
        *,
        run_namespace: Optional[str] = None,
    ) -> List[EvalResult]:
        """评测单轮或多轮对话用例。
        {"question": "有哪些热门推理模型？"}
        {"turns": ["我要做知识库问答", "每天一万次调用", "优先推荐便宜套餐"]}
        """
        questions = self._dialog_turns(case)
        if not questions:
            return []
        # 每次 run 都使用不可预测的独立命名空间；同一 case 的多轮共享会话，跨 run 永不复用 Redis 状态。
        namespace = run_namespace or f"eval_{uuid.uuid4().hex}"
        conv_label = str(case.get("conv_id") or f"case_{case_idx}")
        user_label = str(case.get("user_id") or "user")
        conv_id = f"{namespace}:conv:{conv_label}"
        user_id = f"{namespace}:user:{user_label}"
        history: List[Dict[str, str]] = []#保存当前评测 case 的多轮对话历史
        results: List[EvalResult] = []#保存这个 case 每一轮的评测结果

        for turn_idx, question in enumerate(questions):
            context = self._history_context(history)
            run_meta = await self._run_dialog_turn(       #/chat主链路或agent编排--得到生成真实 Agent 回复
                question=question,
                user_id=user_id,
                conv_id=conv_id,
                case=case,
                turn_idx=turn_idx,
                context=context,
                history=history,
            )
            actual_answer = str(run_meta.get("response", ""))
            expected_points = self._turn_list(case, "expected_points", "expected_points_by_turn", turn_idx)
            forbidden_claims = self._turn_list(case, "forbidden_claims", "forbidden_claims_by_turn", turn_idx)
            hard_check = self._check_hard_rules(
                case=case,
                turn_idx=turn_idx,
                response=actual_answer,
                run_meta=run_meta,
                expected_points=expected_points,
                forbidden_claims=forbidden_claims,
            )
            # 总通过只由关键门禁和 Judge 质量决定。诊断覆盖率单独展示，避免固定词、路由或 RAG 偏好变相一票否决。
            scores = await self._judge.judge(
                question,
                actual_answer,
                context=context or None,
                expected_points=expected_points,
                forbidden_claims=forbidden_claims,
            )
            passed = (
                hard_check.passed
                and not scores.judge_failed
                and scores.overall >= self.PASS_THRESHOLD
            )
            #把用户问题和 Agent 回答追加到历史
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": actual_answer})

            test_id = f"dialog_{case_idx}" if len(questions) == 1 else f"dialog_{case_idx}_turn_{turn_idx}"
            results.append(EvalResult(
                test_id=test_id,
                passed=passed,
                scores={
                    "relevance": scores.relevance,
                    "accuracy": scores.accuracy,
                    "completeness": scores.completeness,
                    "helpfulness": scores.helpfulness,
                    "overall": scores.overall,
                    "rule_score": hard_check.score,
                    "critical_rule_score": hard_check.critical_score,
                },
                detail=self._dialog_detail(question, scores, hard_check),
                metadata={
                    "result_type": "dialog",
                    "participates_in_pass_rate": True,
                    "question": question,
                    "response": actual_answer,
                    "agent_type": run_meta.get("agent_type"),
                    "collaborating_agent_types": run_meta.get("collaborating_agent_types", []),
                    "intent": run_meta.get("intent"),
                    "review_required": run_meta.get("review_required"),
                    "latency_ms": run_meta.get("latency_ms"),
                    "knowledge_used": run_meta.get("knowledge_used"),
                    "business_data_used": run_meta.get("business_data_used"),
                    "tools_used": list(run_meta.get("tools_used") or []),
                    "authoritative_tools_used": list(run_meta.get("authoritative_tools_used") or []),
                    "turn": turn_idx,
                    "conv_id": conv_id,
                    "judge_failed": scores.judge_failed,
                    "judge_error": scores.error,
                    "expected_points": expected_points,
                    "forbidden_claims": forbidden_claims,
                    "critical_rule_passed": hard_check.passed,
                    "critical_rule_score": hard_check.critical_score,
                    "rule_summary": hard_check.summary,
                    "missing_expected_points": hard_check.missing_expected_points,
                    "forbidden_hits": hard_check.forbidden_hits,
                    "route_errors": hard_check.route_errors,
                    "usage_errors": hard_check.usage_errors,
                    "critical_errors": hard_check.critical_errors,
                    "unchecked_required_tools": hard_check.unchecked_required_tools,
                },
            ))

        return results

    async def _run_dialog_turn(
        self,
        *,
        question: str,
        user_id: str,
        conv_id: str,
        case: Dict[str, Any],
        turn_idx: int,
        context: str,
        history: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """优先走完整 /chat 链路；未注入 chat_runner 时退回裸 Orchestrator。"""
        if self._chat_runner is not None:
            return await self._chat_runner(question, user_id, conv_id, case, turn_idx)

        from agents.agent_orchestrator import Request as OrcReq

        orch_req = OrcReq(
            message=question,
            user_id=user_id,
            conv_id=conv_id,
            context=context,
            history=history[-6:] if history else None,
        )
        orch_result = await self._orchestrator.run(orch_req)
        knowledge_used = any(
            record.category == "knowledge" and record.status == "success" and record.authoritative
            for record in orch_result.tool_records
        )
        business_data_used = any(
            record.category in {"public_business", "private_business"}
            and record.status == "success"
            and record.authoritative
            for record in orch_result.tool_records
        )
        return {
            "response": orch_result.response,
            "agent_type": orch_result.agent_type.value,
            "collaborating_agent_types": [
                agent_type.value for agent_type in orch_result.collaborating_agent_types
            ],
            "intent": orch_result.intent.value if orch_result.intent else None,
            "review_required": orch_result.review_required,
            "latency_ms": round(orch_result.latency_ms, 1),
            "tools_used": orch_result.tools_used,
            "authoritative_tools_used": orch_result.authoritative_tools_used,
            "knowledge_used": knowledge_used,
            "business_data_used": business_data_used,
        }

    # 对一轮 Agent 回复做关键门禁和诊断覆盖检查。
    @classmethod
    def _check_hard_rules(
        cls,
        *,
        case: Dict[str, Any],
        turn_idx: int,
        response: str,
        run_meta: Dict[str, Any],
        expected_points: List[str],
        forbidden_claims: List[str],
    ) -> HardRuleCheck:
        soft_checks = 0
        soft_passed = 0
        critical_checks = 0
        critical_passed = 0
        missing_expected_points: List[str] = []
        forbidden_hits: List[str] = []
        route_errors: List[str] = []
        usage_errors: List[str] = []
        critical_errors: List[str] = []
        unchecked_required_tools: List[str] = []

        # 必含要点是表达覆盖度，不再作为一票否决的关键门禁。
        for point in expected_points:
            soft_checks += 1
            if cls._matches_text(response, point):
                soft_passed += 1
            else:
                missing_expected_points.append(point)

        # 禁忌说法属于安全/交易边界关键门禁，但要识别“切勿/不要”等否定语义。
        for claim in forbidden_claims:
            critical_checks += 1
            if cls._matches_forbidden_claim(response, claim):#会识别否定语境（如"不要/切勿/无法"），如果禁忌说法前面有否定词就不算命中
                forbidden_hits.append(claim)
            else:
                critical_passed += 1

        # 意图和 Agent 路由作为诊断覆盖项，不再单独一票否决。
        expected_intent = cls._turn_value(case, "expected_intent", "expected_intents", turn_idx)
        if expected_intent:
            soft_checks += 1
            actual_intent = run_meta.get("intent")
            if actual_intent == expected_intent:
                soft_passed += 1
            else:
                route_errors.append(f"意图不符: expected={expected_intent}, actual={actual_intent}")

        expected_agent_type = cls._turn_value(case, "expected_agent_type", "expected_agent_types", turn_idx)
        if expected_agent_type:
            soft_checks += 1
            actual_agent_type = run_meta.get("agent_type")
            collaborators = {str(item) for item in (run_meta.get("collaborating_agent_types") or [])}
            if actual_agent_type == expected_agent_type or expected_agent_type in collaborators:
                soft_passed += 1
            else:
                route_errors.append(
                    f"Agent 不符: expected={expected_agent_type}, actual={actual_agent_type}, "
                    f"collaborators={sorted(collaborators)}"
                )

        # 人工审核标记属于高风险业务边界，保留为关键门禁。
        expected_review = cls._turn_optional_bool(
            case, "expected_review_required", "expected_review_required_by_turn", turn_idx
        )
        if expected_review is not None:
            critical_checks += 1
            actual_review = bool(run_meta.get("review_required"))
            if actual_review == expected_review:
                critical_passed += 1
            else:
                critical_errors.append(
                    f"关键审核标记不符: expected={expected_review}, actual={actual_review}"
                )

        # 只有明确要求使用实时业务数据时才设为关键门禁；False 表示“不强制”，不是“禁止调用”。
        require_business = cls._turn_optional_bool(
            case, "require_business_data", "require_business_data_by_turn", turn_idx
        )
        if require_business is True:
            critical_checks += 1
            actual_used = run_meta.get("business_data_used")
            if actual_used is True:
                critical_passed += 1
            else:
                critical_errors.append("关键实时数据门禁失败: 未使用 ModelHub Java 后端业务数据")

        # RAG 使用属于回答依据偏好，按诊断规则统计。
        require_knowledge = cls._turn_optional_bool(
            case, "require_knowledge", "require_knowledge_by_turn", turn_idx
        )
        if require_knowledge is True:
            soft_checks += 1
            if run_meta.get("knowledge_used") is True:
                soft_passed += 1
            else:
                usage_errors.append("未使用 knowledge_search")

        def check_tool(tool_name: str, *, critical: bool) -> None:
            nonlocal soft_checks, soft_passed, critical_checks, critical_passed
            aliases = {
                "model_hot": "modelhub_hot_models",
                "model_search": "modelhub_search_models",
                "model_detail": "modelhub_get_model",
                "model_packages": "modelhub_list_packages",
                "package_detail": "modelhub_get_package",
                "package_hot": "modelhub_hot_packages",
            }
            actual_tools = {str(item) for item in (run_meta.get("authoritative_tools_used") or [])}
            if tool_name == "knowledge_search":
                used = run_meta.get("knowledge_used") is True or tool_name in actual_tools
                label = "knowledge_search"
            elif tool_name in {"model_hub", "modelhub", "business_data"}:
                used = run_meta.get("business_data_used") is True
                label = "ModelHub 实时业务工具链路"
            else:
                canonical = aliases.get(str(tool_name), str(tool_name))
                used = canonical in actual_tools
                label = canonical

            if critical:
                critical_checks += 1
                if used is True:
                    critical_passed += 1
                else:
                    critical_errors.append(f"关键工具门禁失败: 未使用 {label}")
            else:
                soft_checks += 1
                if used is True:
                    soft_passed += 1
                else:
                    usage_errors.append(f"未使用 {label}")

        for tool_name in cls._turn_list(case, "required_tools", "required_tools_by_turn", turn_idx):
            check_tool(tool_name, critical=False)
        for tool_name in cls._turn_list(
            case, "critical_required_tools", "critical_required_tools_by_turn", turn_idx
        ):
            check_tool(tool_name, critical=True)

        score = round(soft_passed / soft_checks, 4) if soft_checks else 1.0
        critical_score = round(critical_passed / critical_checks, 4) if critical_checks else 1.0
        return HardRuleCheck(
            passed=not forbidden_hits and not critical_errors,
            score=score,
            critical_score=critical_score,
            missing_expected_points=missing_expected_points,
            forbidden_hits=forbidden_hits,
            route_errors=route_errors,
            usage_errors=usage_errors,
            critical_errors=critical_errors,
            unchecked_required_tools=unchecked_required_tools,
        )

    @staticmethod
    def _dialog_detail(question: str, scores: QualityScores, hard_check: HardRuleCheck) -> str:
        if scores.judge_failed:
            return f"Q: {question[:30]}... → Judge 失败；{hard_check.summary}"
        gate = "通过" if hard_check.passed else "失败"
        return (
            f"Q: {question[:30]}... → 综合评分 {scores.overall:.3f}；"
            f"关键门禁 {gate}；规则覆盖 {hard_check.score:.3f}"
        )

    @classmethod
    def _turn_list(cls, case: Dict[str, Any], scalar_key: str, list_key: str, turn_idx: int) -> List[str]:
        values = case.get(list_key)
        if isinstance(values, list) and turn_idx < len(values) and isinstance(values[turn_idx], list):
            return [str(v) for v in values[turn_idx] if str(v).strip()]
        raw = case.get(scalar_key) or []
        return [str(v) for v in raw if str(v).strip()]

    @staticmethod
    def _turn_value(case: Dict[str, Any], scalar_key: str, list_key: str, turn_idx: int) -> Optional[str]:
        values = case.get(list_key)
        if isinstance(values, list) and turn_idx < len(values):
            value = values[turn_idx]
            return str(value) if value is not None else None
        value = case.get(scalar_key)
        return str(value) if value is not None else None

    @staticmethod
    def _turn_optional_bool(
        case: Dict[str, Any], scalar_key: str, list_key: str, turn_idx: int
    ) -> Optional[bool]:
        values = case.get(list_key)
        if isinstance(values, list) and turn_idx < len(values):
            value = values[turn_idx]
            return bool(value) if value is not None else None
        if scalar_key not in case:
            return None
        value = case.get(scalar_key)
        return bool(value) if value is not None else None

    @classmethod
    def _matches_text(cls, text: str, rule: str) -> bool:
        """支持用 | 或 / 写同义备选，例如 库存|售罄。"""
        normalized_text = cls._normalize_for_match(text)
        alternatives = [part.strip() for part in str(rule).replace("/", "|").split("|") if part.strip()]
        return any(cls._normalize_for_match(alt) in normalized_text for alt in alternatives)

    @classmethod
    def _matches_forbidden_claim(cls, text: str, rule: str) -> bool:
        """匹配肯定式危险表达，忽略“不要/切勿/无法”等安全否定语境。
        用于判断 text 里有没有出现 rule 指定的敏感/危险说法。
        如果是肯定式出现，返回 True；
        如果前面有“不要、禁止、无法、不能”等否定词，就认为不是危险承诺，返回 False 或继续找下一个匹配。
        """
        normalized_text = cls._normalize_for_match(text)
        alternatives = [part.strip() for part in str(rule).replace("/", "|").split("|") if part.strip()]
        negations = (
            "不要", "请勿", "切勿", "禁止", "不得", "不能", "无法", "不会",
            "未", "没有", "不应", "无需", "避免", "不可", "绝不能",
        )
        for alternative in alternatives:
            needle = cls._normalize_for_match(alternative)
            if not needle:
                continue
            start = 0
            while True:
                index = normalized_text.find(needle, start)
                if index < 0:
                    break
                prefix = normalized_text[max(0, index - 16):index]
                if not any(negation in prefix for negation in negations):
                    return True
                start = index + max(1, len(needle))
        return False

    @staticmethod
    def _normalize_for_match(value: str) -> str:
        normalized = str(value).lower().replace("tokens", "token")
        normalized = re.sub(r"[\s,，_]+", "", normalized)#去掉空格、英文逗号、中文逗号、下划线。
        normalized = normalized.replace("一万", "10000").replace("1万", "10000")#把“一万”和“1万”统一成 10000
        return normalized

    @staticmethod
    def _dialog_turns(case: Dict[str, Any]) -> List[str]:
        turns = case.get("turns")
        if isinstance(turns, list):
            return [str(t) for t in turns if str(t).strip()]
        question = case.get("question")
        return [str(question)] if question else []

    @staticmethod
    def _history_context(history: List[Dict[str, str]]) -> str:
        if not history:
            return ""
        lines = [f"{m['role']}: {m['content']}" for m in history[-8:]]
        return "[评测多轮历史]\n" + "\n".join(lines)

    def _detect_regressions(self, current: Dict[str, float]) -> List[str]:
        """与上一次评测对比，找出退化超过 5% 的指标。"""
        prev_report = self._history[-1] if self._history else self._baseline#优先和上一次评测比；如果没有上一次，就和磁盘里的 baseline 比。
        if prev_report is None:
            return []
        prev = {**prev_report.avg_scores, **prev_report.diagnostic_scores}
        regressions = []
        for metric, value in current.items():
            if metric in prev and prev[metric] > 0:
                delta = (value - prev[metric]) / prev[metric]
                if delta < -0.05:#如果当前指标比之前低超过 5%：
                    regressions.append(#加入退化列表。
                        f"{metric}: {prev[metric]:.3f} → {value:.3f} (退化 {abs(delta):.1%})"
                    )
        return regressions
    # 根据分数生成建议
    def _recommendations(
        self,
        scores: Dict[str, float],
        diagnostic_scores: Dict[str, float],
    ) -> List[str]:
        recs = []
        if diagnostic_scores.get("intent_accuracy", 1.0) < 0.90:
            recs.append("诊断项：意图识别准确率 < 90%，建议增加 Few-shot 示例，或对低 F1 的意图类别补充训练数据")
        if scores.get("judge_failed_rate", 0.0) > 0.05:
            recs.append("Judge 失败率偏高：本轮对话质量均分不完全可信，请先检查 LLM 网络/API 配置后再看质量分")
        if scores.get("critical_rule_pass_rate", 1.0) < 1.0:
            recs.append("关键门禁未全部通过：优先检查隐私安全、交易写操作边界、实时业务数据来源和人工审核标记")
        if scores.get("rule_score", 1.0) < self.RULE_COVERAGE_THRESHOLD:
            recs.append("诊断规则覆盖偏低：检查语义要点、意图/Agent 路由和知识库使用；这些规则不应使用脆弱的固定词一票否决")
        if scores.get("relevance", 1.0) < 0.75:
            recs.append("相关性偏低：检查 Agent system_prompt，确保 Agent 聚焦于用户问题")
        if scores.get("completeness", 1.0) < 0.75:
            recs.append("完整性偏低：Agent 可能过早结束回答，考虑在 prompt 中要求提供完整解决方案")
        if scores.get("helpfulness", 1.0) < 0.75:
            recs.append("有用性偏低：回答可能过于抽象，考虑要求 Agent 提供具体操作步骤")
        if not recs:
            recs.append("所有指标均达标，继续保持")
        return recs

    @property
    def history(self) -> List[EvalReport]:
        return self._history

    def _load_baseline(self) -> Optional[EvalReport]:
        if not self._baseline_path or not self._baseline_path.exists():
            return None
        try:
            data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
            return self._report_from_dict(data)
        except Exception as ex:
            logger.warning(f"读取评测基线失败: {ex}")
            return None

    def _save_baseline(self, report: EvalReport) -> None:
        if not self._baseline_path:
            return
        try:
            self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
            self._baseline_path.write_text(
                json.dumps(asdict(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._baseline = report
        except Exception as ex:
            logger.warning(f"保存评测基线失败: {ex}")

    @staticmethod
    def _report_from_dict(data: Dict[str, Any]) -> EvalReport:
        return EvalReport(
            timestamp=data.get("timestamp", ""),
            total=int(data.get("total", 0)),
            passed=int(data.get("passed", 0)),
            pass_rate=float(data.get("pass_rate", 0.0)),
            avg_scores=dict(data.get("avg_scores", {})),
            diagnostic_scores=dict(data.get("diagnostic_scores", {})),
            regressions=list(data.get("regressions", [])),
            recommendations=list(data.get("recommendations", [])),
            results=[
                EvalResult(
                    test_id=r.get("test_id", ""),
                    passed=bool(r.get("passed", False)),
                    scores=dict(r.get("scores", {})),
                    detail=r.get("detail", ""),
                    metadata=dict(r.get("metadata", {})),
                )
                for r in data.get("results", [])
            ],
        )


# ── 内置测试用例（开箱即用）──────────────────────────────────────────────────

DEFAULT_INTENT_CASES: List[IntentTestCase] = [
    IntentTestCase("做中文知识库问答应该选哪个模型？", "model_search"),
    IntentTestCase("每天一万次问答一个月大约多少钱？", "cost_estimation"),
    IntentTestCase("限时 Token 套餐为什么抢不到？", "token_package"),
    IntentTestCase("API 返回 429 应该怎么排查？", "api_support"),
    IntentTestCase("最近 Token 为什么消耗这么快？", "usage_analysis"),
    IntentTestCase("这个账号是否存在批量刷套餐风险？", "risk"),
    IntentTestCase("我要投诉，需要平台侧确认！", "manual_review"),
]

DEFAULT_DIALOG_CASES: List[Dict[str, Any]] = [
    {
        "question": "目前有哪些热门推理模型？",
        "expected_intent": "model_search",
        "expected_agent_type": "model_advisor",
        "require_business_data": True,
        "expected_points": ["模型", "推理", "适用|适合|场景|能力定位"],
        "forbidden_claims": ["已经替你购买", "保证参数完全正确"],
    },
    {
        "question": "限时 Token 套餐为什么可能抢不到？",
        "expected_intent": "token_package",
        "expected_agent_type": "quota_order",
        "require_knowledge": True,#检查是否走了知识库链路
        "expected_points": ["库存|售罄", "时间|开售", "限购|重复下单", "登录|订单|支付"],
        "forbidden_claims": ["已经帮你抢到", "保证抢到", "已经完成充值"],
    },
    {
        "question": "每天一万次问答，平均输入2000、输出500 Token，帮我估算月成本",
        "expected_intent": "cost_estimation",
        "expected_agent_type": "cost_optimizer",
        "require_business_data": True,
        "expected_points": ["输入", "输出", "调用次数|一万", "月|成本", "假设|口径"],
        "forbidden_claims": ["保证不会超预算", "已经扣费"],
    },
    {
        "question": "API 返回 429，应该按什么顺序排查？",
        "expected_intent": "api_support",
        "expected_agent_type": "api_support",
        "require_knowledge": True,
        "expected_points": ["限流|频率", "重试|退避", "额度|并发", "排查"],
        "forbidden_claims": ["粘贴完整 API Key", "已经解除限流"],
    },
    {
        "turns": ["我要做中文知识库问答", "每天大约调用一万次", "有便宜的 Token 套餐优先推荐"],
        "expected_intents": ["model_search", "cost_estimation", "token_package"],
        "expected_agent_types": ["model_advisor", "cost_optimizer", "quota_order"],
        "require_business_data_by_turn": [False, True, True],
        "expected_points_by_turn": [
            ["知识库|检索", "模型|embedding|向量"],
            ["一万|1万|10000|10,000", "调用量|调用次数|日均调用", "输入|输出|Token"],
            ["套餐", "价格|便宜", "额度|有效期"],
        ],
        "forbidden_claims": ["已经帮你下单", "已经帮你抢购", "已经完成支付"],
    },
]
