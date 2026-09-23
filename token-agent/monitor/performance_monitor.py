"""
亮点：利用 Monitor 监控 Agent 在线表现

流程：
服务启动
  -> PerformanceMonitor.start()
  -> 创建后台 _loop()
  -> 每 10 秒执行 _collect()
  -> 读取 Agent/Tool 统计
  -> agent:Z-score 异常检测（超过敏感度，返回异常信息） + 阈值告警（Agent 成功率低于 0.90、延迟高于 3000ms。）-> 回写 routing_penalty 给 Orchestrator->生成路由优化建议(调用次数>10且成功率<0.85)
  -> tool:阈值告警(tool成功率低于 0.95、延迟高于 5000ms)->生成优化建议（工具连续失败 3 次以上）
核心问题：如何利用 Monitor 监控 Agent 的在线表现？
本模块的答案：
  1. 实时采集 —— 每隔 N 秒从 Orchestrator 和 ToolManager 拉取最新统计
  2. 异常检测 —— Z-score 统计方法，自动发现指标突变
  3. 路由反馈 —— 将 Agent 成功率/延迟写回 Orchestrator，
     Orchestrator 的 _best_agent() 会据此动态调整路由权重
  4. 优化建议 —— 基于规则生成可操作的优化建议（不是空话）
  5. 告警 —— 超阈值时打日志 + 可选 Webhook
"""
import asyncio
import logging
import statistics
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

import httpx
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────────────
#告警等级
class Severity(Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"

#告警数据结构 Alert
@dataclass
class Alert:
    severity:    Severity
    metric:      str #哪个指标出问题，例如 agent_success_rate:general_0
    message:     str #告警描述。
    value:       float #当前指标值。
    threshold:   float #阈值
    ts:          str = field(default_factory=lambda: datetime.now().isoformat()) #告警时间，默认自动生成当前时间。
    resolved:    bool = False #是否已恢复，默认 False。


@dataclass
class Suggestion:
    """可操作的优化建议。"""
    title:       str    #建议标题。
    detail:      str    #详细说明。
    action:      str    # 具体操作步骤
    priority:    int    # 1-10 越大越重要


# ── 异常检测 ──────────────────────────────────────────────────────────────────

class AnomalyDetector:
    """
    基于滑动窗口 Z-score 的异常检测。

    Z-score = |当前值 - 均值| / 标准差
    超过 sensitivity 则判定为异常。
    """

    def __init__(self, window: int = 60, sensitivity: float = 2.5):
        self._window      = window #每个指标最多保存最近 60 个数据点。
        self._sensitivity = sensitivity
        #创建一个字典，用来保存每个指标最近 window 次的数值；
        #如果某个指标第一次出现，就自动给它创建一个最多保存 window 个 float 的 deque。
        self._history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window))

    def record(self, metric: str, value: float) -> Optional[Dict[str, Any]]:
        """记录一个数据点，如果异常则返回异常信息，否则返回 None。"""
        #取出这个指标的历史队列，并加入当前值。
        buf = self._history[metric]
        buf.append(value)

        if len(buf) < self._window // 2:
            return None  # 如果数据量还不够窗口一半，不做异常检测。
        #计算均值和标准差。
        mean  = statistics.mean(buf)
        stdev = statistics.stdev(buf) if len(buf) > 1 else 0.0
        if stdev == 0:
            return None#如果标准差是 0，说明历史数据没有波动，无法计算 Z-score。

        z = abs(value - mean) / stdev #计算当前值偏离程度。
        if z > self._sensitivity: #如果超过敏感度，就返回异常信息。
            return {
                "metric":   metric,
                "value":    value,
                "mean":     mean,
                "z_score":  round(z, 2),#保留2位小数
                #medium：2.5 < z <= 3.75   high：z > 3.75
                "severity": "high" if z > self._sensitivity * 1.5 else "medium",#当前 severity 是预留字段/半成品字段，但没被业务使用。
            }
        return None


# ── 性能监控器 ────────────────────────────────────────────────────────────────

class PerformanceMonitor:
    """
    Agent 在线表现监控。

    与 Orchestrator 的联动：
      Monitor 采集 → 发现某 Agent 成功率下降 →
      Orchestrator.get_stats() 中该 Agent 的 routing_score 自动降低 →
      _best_agent() 路由时自动绕开该 Agent

    这就是"利用 Monitor 监控在线表现"的闭环。
    """

    # 告警阈值
    THRESHOLDS = {
        "agent_success_rate":  (0.90, Severity.ERROR,   "less_than"),#Agent 成功率低于 0.90，报 ERROR
        "tool_success_rate":   (0.95, Severity.WARNING,  "less_than"),#工具成功率低于 0.95，报 WARNING。
        "agent_avg_ms":        (3000, Severity.WARNING,  "greater_than"),#Agent 平均耗时超过 3000ms，报 WARNING。
        "tool_avg_ms":         (5000, Severity.ERROR,    "greater_than"),#工具平均耗时超过 5000ms，报 ERROR。
    }

    def __init__(
        self,
        orchestrator,#提供 Agent 统计。
        tool_manager,#提供工具统计。
        interval_s:       float = 10.0,#采集间隔，默认 10 秒。
        webhook_url:      Optional[str] = None,#Webhook URL，用于发送告警。
        prometheus_port:  Optional[int] = None,   # None = 不启动
    ):
        self._orchestrator = orchestrator
        self._tool_manager = tool_manager
        self._interval     = interval_s#采集间隔
        self._webhook      = webhook_url
        self._detector     = AnomalyDetector()#异常检测器。

        self._alerts:      List[Alert]      = []#告警列表。
        self._suggestions: List[Suggestion] = []#优化建议列表。
        self._active       = False#是否运行中。
        self._task:        Optional[asyncio.Task] = None#异步任务。

        # Prometheus 指标（可选） 时序数据库监控系统
        self._prom: Dict[str, Any] = {}
        if prometheus_port:
            self._setup_prometheus(prometheus_port)

    def _setup_prometheus(self, port: int) -> None:
        self._prom = {
            "agent_success_rate": Gauge("agent_success_rate", "Agent 成功率", ["agent"]),
            "agent_latency_ms":   Histogram("agent_latency_ms", "Agent 延迟", ["agent"]),
            "tool_success_rate":  Gauge("tool_success_rate", "工具成功率", ["tool"]),
            "requests_total":     Counter("requests_total", "总请求数"),
        }
        start_http_server(port)#启动 Prometheus HTTP 服务。
        logger.info(f"Prometheus 已启动: :{port}")

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._active:#如果已经启动，直接返回，避免重复启动。
            return
        self._active = True
        self._task   = asyncio.create_task(self._loop())
        logger.info(f"Monitor 已启动，采集间隔 {self._interval}s")

    async def stop(self) -> None:
        self._active = False
        if self._task:
            self._task.cancel()#取消后台任务
            try:
                await self._task
            except asyncio.CancelledError:#说明任务正常被取消，直接忽略
                pass

    # ── 采集循环 ──────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._active:
            try:
                await self._collect()
            except Exception as ex:
                logger.error(f"Monitor 采集异常: {ex}")
            await asyncio.sleep(self._interval)#每隔 self._interval 秒采集一次。

    async def _collect(self) -> None:
        """
        采集 Agent 和工具的实时统计，检测异常，生成建议。

        关键：这里读取的 stats 就是 Orchestrator/ToolManager 在处理请求时，实时更新的数据。
        """
        agent_stats = self._orchestrator.get_stats()
        tool_stats  = self._tool_manager.get_stats()
        routing_penalties: Dict[str, float] = {}#这个字典会保存每个 Agent 的路由惩罚值，后面写回 Orchestrator。

        # ── Agent 指标 ────────────────────────────────────────────────────────
        for agent_key, s in agent_stats.items():
            sr  = s["success_rate"]
            ms  = s["avg_ms"]

            # 异常检测
            #某 Agent 的成功率是否异常波动、平均延迟是否异常波动
            for metric, value in [("agent_success_rate", sr), ("agent_avg_ms", ms)]:
                anomaly = self._detector.record(f"{metric}:{agent_key}", value)
                if anomaly:#如果异常，就打 warning 日志。
                    logger.warning(f"异常检测 [{agent_key}] {metric}={value:.3f} z={anomaly['z_score']}")

            # 如果触发阈值，创建Alert，并加入告警列表
            self._check_threshold("agent_success_rate", sr, agent_key)
            self._check_threshold("agent_avg_ms", ms, agent_key)

            # Prometheus
            if "agent_success_rate" in self._prom:
                #如果启用了 Prometheus，就把 Agent 成功率和延迟上报给 Prometheus。
                #实际用途是后面可以做监控图表，比如： local_guide_0 成功率趋势、deal_order_0 平均延迟、哪个 Agent 最近变慢了
                self._prom["agent_success_rate"].labels(agent=agent_key).set(sr)
                self._prom["agent_latency_ms"].labels(agent=agent_key).observe(ms)
            #计算路由惩罚：
            routing_penalties[agent_key] = self._routing_penalty(sr, ms)

        # ── 工具指标 ──────────────────────────────────────────────────────────
        for tool_name, s in tool_stats.items():
            sr = s["success_rate"]
            ms = s["avg_latency_ms"]
            cf = s["consecutive_fails"]
            # 如果触发阈值，创建Alert，并加入告警列表
            self._check_threshold("tool_success_rate", sr, tool_name)
            self._check_threshold("tool_avg_ms", ms, tool_name)

            if "tool_success_rate" in self._prom:
                self._prom["tool_success_rate"].labels(tool=tool_name).set(sr)

            # 连续失败 → 生成具体建议
            if cf >= 3:
                self._add_suggestion(Suggestion(
                    title=f"工具 {tool_name} 连续失败 {cf} 次",
                    detail=f"成功率 {sr:.1%}，平均延迟 {ms:.0f}ms，熔断状态: {s['circuit_state']}",
                    action="1. 检查工具依赖服务是否正常\n2. 查看错误日志\n3. 考虑增加超时时间或降级策略",
                    priority=9,
                ))

        # ── 路由优化建议 ──────────────────────────────────────────────────────
        #动态检查 orchestrator 有没有 update_routing_penalties 方法。
        updater = getattr(self._orchestrator, "update_routing_penalties", None)
        if updater:
            updater(routing_penalties)
        # 基于 Agent 在线表现生成路由优化建议。
        self._generate_routing_suggestions(agent_stats)

    #路由惩罚
    @staticmethod
    def _routing_penalty(success_rate: float, avg_ms: float) -> float:
        """把在线表现转成 0-0.9 的路由降权系数。"""
        penalty = 0.0
        if success_rate < 0.90:#如果成功率低于 90%
            penalty += min(0.5, (0.90 - success_rate) * 2)#最多因为成功率问题增加 0.5 惩罚。
        if avg_ms > 3000:
            penalty += min(0.4, (avg_ms - 3000) / 10000)#最多因为延迟问题增加 0.4 惩罚。
        return min(penalty, 0.9)#总惩罚最多 0.9，不会把 Agent 完全打成 0

    #阈值检查
    def _check_threshold(self, metric: str, value: float, label: str) -> None:
        if metric not in self.THRESHOLDS:
            return
        #取出阈值配置：
        threshold, severity, operator = self.THRESHOLDS[metric]
        triggered = (operator == "less_than" and value < threshold) or \
                    (operator == "greater_than" and value > threshold)
        #如果触发，就创建 Alert
        if triggered:
            alert = Alert(
                severity=severity,
                metric=f"{metric}:{label}",
                message=f"{label} 的 {metric} = {value:.3f}，阈值 {threshold}",
                value=value,
                threshold=threshold,
            )
            self._alerts.append(alert)#加入告警列表
            logger.warning(f"[{severity.value.upper()}] {alert.message}")
            # 异步发送 Webhook（不阻塞采集循环）
            if self._webhook:#如果配置了 webhook
                asyncio.create_task(self._send_webhook(alert))

    def _generate_routing_suggestions(self, agent_stats: Dict[str, Any]) -> None:
        """
        基于 Agent 在线表现生成路由优化建议。
        这是 Monitor → Orchestrator 反馈闭环的体现。
        """
        for agent_key, s in agent_stats.items():
            #调用次数超过 10 次，并且成功率低于 85%
            if s["success_rate"] < 0.85 and s["total"] > 10:
                self._add_suggestion(Suggestion(
                    title=f"Agent {agent_key} 成功率偏低",
                    detail=f"成功率 {s['success_rate']:.1%}，路由评分 {s['routing_score']:.3f}",
                    action=(
                        "Orchestrator 的 _best_agent() 已自动降低该 Agent 的路由权重。\n"
                        "建议：1. 检查 system_prompt 是否需要优化\n"
                        "     2. 检查该类型问题的复杂度是否超出 Agent 能力\n"
                        "     3. 考虑增加同类型 Agent 实例"
                    ),
                    priority=8,
                ))

    def _add_suggestion(self, s: Suggestion) -> None:
        # 去重：相同 title 不重复添加
        if not any(x.title == s.title for x in self._suggestions):
            self._suggestions.append(s)
            logger.info(f"优化建议 [P{s.priority}]: {s.title}")

    #用 httpx.AsyncClient 发送 POST 请求
    async def _send_webhook(self, alert: Alert) -> None:
        """
        这个方法就是把系统告警发给外部通知系统，比如企业微信、钉钉、Slack、告警平台或者你自己的后端接口。
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:#创建一个异步 HTTP 客户端，超时时间 5 秒。
                #向 self._webhook 这个地址发送 POST 请求。请求体是：asdict(alert)
                await c.post(self._webhook, json=asdict(alert))  #asdict(alert) 会把 dataclass 转成字典。
        except Exception as ex:
            logger.error(f"Webhook 发送失败: {ex}")

    # ── 查询接口 ：在 FastAPI 的 /monitor 接口里调用的。────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """返回当前监控摘要，供 API 层暴露。"""
        return {
            "agent_stats":   self._orchestrator.get_stats(),
            "tool_stats":    self._tool_manager.get_stats(),
            "active_alerts": [asdict(a) for a in self._alerts if not a.resolved][-10:],#只保留还没有解决的告警，返回最近 10 条未解决告警
            "suggestions":   [
                {"title": s.title, "action": s.action, "priority": s.priority}
                for s in sorted(self._suggestions, key=lambda x: -x.priority)[:5]#按优先级倒序，返回前 5 条优化建议。
            ],
        }
