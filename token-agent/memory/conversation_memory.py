"""
亮点：多轮对话记忆管理

三级记忆架构，模拟人类记忆机制：
  1. 工作记忆（Redis）—— 当前会话的最近 N 条消息，毫秒级读写
  2. 情景记忆（Milvus）—— 跨会话的历史对话，按语义相似度检索
  3. 用户画像（Milvus）—— 从对话中提炼的长期偏好和实体

关键设计：
  - 上下文构建时三级记忆融合，按重要性 + 时效性排序
  - 工作记忆超过阈值时自动压缩（LLM 摘要），防止 context 爆炸
  - Milvus 模式可使用中文 embedding 模型，提升中文语义召回效果
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import redis
from anthropic import AsyncAnthropic

from storage.postgres_store import PostgresMessageStore
from storage.vector_store import MilvusTextStore, user_filter

logger = logging.getLogger(__name__)


class MsgRole(Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


@dataclass
class Message:
    role:       MsgRole
    content:    str
    timestamp:  datetime = field(default_factory=datetime.now)#默认值是“创建对象时的当前时间”。
    metadata:   Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryContext:
    """传给 Agent 的完整上下文。"""
    recent_messages:  List[Message]   # 工作记忆：最近对话
    relevant_history: List[str]       # 情景记忆：语义相关的历史片段
    user_profile:     Dict[str, Any]  # 用户画像：偏好、常用实体
    summary:          str             # 当前会话摘要（压缩后）

    @staticmethod
    def _clean(text: str) -> str:
        """移除 Unicode 代理字符，防止编码错误。"""
        return text.encode("utf-8", errors="ignore").decode("utf-8")

    def to_prompt_text(self) -> str:
        """将记忆上下文格式化为 LLM 可用的文本。"""
        parts = []
        if self.summary:
            parts.append(f"[会话摘要]\n{self._clean(self.summary)}")
        if self.relevant_history:
            parts.append("[相关历史]\n" + "\n".join(f"- {self._clean(h)}" for h in self.relevant_history[:3]))
        if self.user_profile:
            parts.append(f"[用户画像]\n{json.dumps(self.user_profile, ensure_ascii=True)}")
        if self.recent_messages:
            parts.append("[最近对话]")
            for m in self.recent_messages:
                parts.append(f"{m.role.value}: {self._clean(m.content)}")
        return "\n\n".join(parts)


class MemoryManager:
    """
    三级记忆管理器。

    工作记忆存 Redis（TTL 24h），情景记忆和用户画像存 Milvus（持久化）。
    """

    WORKING_MAX   = 20    # 工作记忆最大条数，超过则触发压缩
    COMPRESS_AT   = 15    # 达到此条数时压缩，保留摘要 + 最近 5 条
    HISTORY_TOP_K = 5     # 情景记忆检索返回条数

    def __init__(
        self,
        redis_url:    str = "redis://localhost:6379/0",
        api_key:      str = "",
        base_url:     Optional[str] = None,
        model:        str = "claude-3-5-sonnet-20241022",
        milvus_uri:   str = "http://localhost:19530",
        milvus_token: Optional[str] = None,
        milvus_dim:   int = 256,
        milvus_episodic_collection: str = "echomind_episodic",
        milvus_profile_collection:  str = "echomind_user_profile",
        embedding_backend: str = "stable",
        embedding_model: str = "",
        query_instruction: str = "",
        embedding_device: str = "",
        database_url: str = "",
    ):
        #初始化 Anthropic 客户端。
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self._model  = model

        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._pg_store = PostgresMessageStore(database_url) if database_url else None
        self._episodic = MilvusTextStore(
            collection_name=milvus_episodic_collection,
            uri=milvus_uri,
            token=milvus_token,
            dim=milvus_dim,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            query_instruction=query_instruction,
            embedding_device=embedding_device,
        )
        self._profile = MilvusTextStore(
            collection_name=milvus_profile_collection,
            uri=milvus_uri,
            token=milvus_token,
            dim=milvus_dim,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            query_instruction=query_instruction,
            embedding_device=embedding_device,
        )
        logger.info(f"记忆向量后端: Milvus {milvus_uri} / {embedding_backend} {embedding_model or '(stable hash)'}")

    # ── 写入 ──────────────────────────────────────────────────────────────────

    async def add_message(
        self,
        user_id: str,
        conv_id: str,
        role:    MsgRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        persist_audit: bool = True,
    ) -> None:
        """将一条消息写入工作记忆，超阈值时自动压缩。"""
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        clean_metadata = {
            self._safe_text(k): self._safe_metadata_value(v)
            for k, v in (metadata or {}).items()
        }
        msg = Message(role=role, content=self._safe_text(content), metadata=clean_metadata)
        key = self._wm_key(user_id, conv_id)#生成 Redis key

        # 追加到 Redis 列表（左推，最新在前）
        self._redis.lpush(key, json.dumps({#把消息转成 JSON 字符串。
            "role":      msg.role.value,
            "content":   msg.content,
            "ts":        msg.timestamp.isoformat(),#把时间转成 ISO 字符串
            "metadata":  msg.metadata,
        }))
        self._redis.expire(key, 86400)  # 24h TTL

        if persist_audit and self._pg_store:
            await self._pg_store.add_message(user_id, conv_id, role.value, msg.content, msg.metadata)

        # 超过压缩阈值时触发压缩  llen(key) 获取 Redis 列表长度。
        if persist_audit and self._redis.llen(key) >= self.COMPRESS_AT:
            await self._compress(user_id, conv_id)

    async def update_profile(self, user_id: str, conv_id: str) -> None:
        """
        从当前工作记忆中提炼用户偏好，更新用户画像。
        用 LLM 提炼偏好，然后存入 Milvus。
        """
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        messages = await self._get_working_memory(user_id, conv_id)
        if not messages:
            return
        #拼接最近 10 条消息并构造提示词。
        text = self._safe_text("\n".join(f"{m.role.value}: {m.content}" for m in messages[-10:]))
        prompt = f"""从以下对话中提炼用户偏好和关键实体，返回 JSON。
对话:
{text}

返回格式: {{"preferences": ["..."], "entities": {{"产品": [], "问题类型": []}}}}"""
        prompt = self._safe_text(prompt)

        try:
            #调用 LLM 并存画像。
            resp = await self._client.messages.create(
                model=self._model, max_tokens=512, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            profile_data = json.loads(raw[s:e])

            doc_id = f"{user_id}_profile_{conv_id}"
            doc_text = self._safe_text(json.dumps(profile_data, ensure_ascii=False))

            self._profile.add_texts([{
                "id": doc_id,
                "text": doc_text,
                "title": "user_profile",
                "user_id": user_id,
                "conv_id": conv_id,
                "kind": "profile",
                "metadata": profile_data,
                "ts": datetime.now().isoformat(),
            }])
            logger.info(f"用户画像已更新: {user_id}")
        except Exception as ex:
            logger.warning(f"更新用户画像失败: {ex}")

    # ── 读取 ──────────────────────────────────────────────────────────────────

    async def get_context(self, user_id: str, conv_id: str, query: str = "") -> MemoryContext:
        """
        构建完整的记忆上下文。

        query 用于从情景记忆中检索语义相关的历史片段。
        """
        # 1. 工作记忆（当前会话最近消息）
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        query = self._safe_text(query)

        recent = await self._get_working_memory(user_id, conv_id)

        # 2. 情景记忆（跨会话语义检索）
        history = await self._search_episodic(user_id, query or (recent[-1].content if recent else ""))

        # 3. 用户画像
        profile = await self._get_profile(user_id)

        # 4. 会话摘要（如果已压缩过）
        summary = self._redis.get(self._summary_key(user_id, conv_id)) or ""

        return MemoryContext(
            recent_messages=recent,
            relevant_history=history,
            user_profile=profile,
            summary=summary,
        )

    # ── 压缩（防止 context 爆炸）─────────────────────────────────────────────

    async def _compress(self, user_id: str, conv_id: str) -> None:
        """
        工作记忆压缩：
          1. 用 LLM 对旧消息生成摘要
          2. 摘要存 Redis（覆盖旧摘要）
          3. 旧消息存入情景记忆（Milvus）供跨会话检索
          4. 工作记忆只保留最近 5 条
        """
        key = self._wm_key(user_id, conv_id)
        # 拍下当前列表的完整快照，后续用于 CAS 比较
        snapshot_raw = self._redis.lrange(key, 0, -1)
        messages = self._messages_from_raws(snapshot_raw)
        if len(messages) < self.COMPRESS_AT:
            return

        to_compress = messages[:-5]   # 保留最近 5 条

        # LLM 摘要
        text = self._safe_text("\n".join(f"{m.role.value}: {m.content}" for m in to_compress))
        prompt = self._safe_text(f"用 2-3 句话总结以下对话的关键信息：\n{text}")
        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = self._safe_text(resp.content[0].text).strip()
        except Exception:
            summary = f"对话包含 {len(to_compress)} 条消息（摘要生成失败）"

        skey = self._summary_key(user_id, conv_id)
        #原子提交：Redis WATCH/MULTI/EXEC 事务，裁剪列表 + 写入摘要
        if not self._commit_compression(key, skey, snapshot_raw, summary):
            logger.info("工作记忆在压缩期间已被其他压缩修改，本轮安全放弃提交")
            return

        # 情景归档：将摘要写入 Milvus，供未来跨会话语义检索
        await self._store_episodic(user_id, conv_id, text, summary)
        logger.info(f"工作记忆压缩完成: {user_id}/{conv_id}，摘要 {len(summary)} 字")

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _get_working_memory(self, user_id: str, conv_id: str) -> List[Message]:
        key  = self._wm_key(user_id, conv_id)
        raws = self._redis.lrange(key, 0, self.WORKING_MAX - 1)#取最多 20 条
        return self._messages_from_raws(raws)

    @staticmethod
    def _messages_from_raws(raws: List[str]) -> List[Message]:
        msgs = []
        for raw in reversed(raws):  # Redis lpush 最新在前，reversed 还原时序
            d = json.loads(raw)#把 JSON 字符串变回字典。
            msgs.append(Message(
                role=MsgRole(d["role"]),
                content=d["content"],
                timestamp=datetime.fromisoformat(d["ts"]),#把 ISO 字符串转回时间对象。
                metadata=d.get("metadata", {}),
            ))
        return msgs

    def _commit_compression(
        self,
        key: str,
        summary_key: str,
        snapshot_raw: List[str],
        summary: str,
    ) -> bool:
        """解决的是多个协程同时压缩同一用户会话的问题："""
        for _ in range(5):#最多重试 5 次
            #pipe 是 Redis 的 Pipeline（管道） 对象，核心作用是把多条命令打包一次性发给服务器，避免逐条往返的网络开销。
            with self._redis.pipeline() as pipe:# 创建管道
                try:
                    # 监听 key 和 summary_key，防止其他协程修改
                    pipe.watch(key, summary_key)# 1.监听（乐观锁）
                    # 获取当前列表的最新内容
                    current = pipe.lrange(key, 0, -1)# 2. 读取当前列表
                    # 校验1：如果当前列表长度小于快照长度，说明被别人删过了
                    if len(current) < len(snapshot_raw):
                        # 取消监听，避免误修改
                        pipe.unwatch()
                        return False
                    # 校验2：快照部分必须完全一致（说明没被改过）
                    if snapshot_raw and current[-len(snapshot_raw):] != snapshot_raw:
                        # 取消监听，避免误修改
                        pipe.unwatch()
                        return False
                    # 通过校验 → 计算保留范围
                    concurrent_prefix = current[:len(current) - len(snapshot_raw)] if snapshot_raw else current# 压缩期间新推入的消息
                    keep_end = len(concurrent_prefix) + min(5, len(snapshot_raw)) - 1# 保留新消息 + 最近5条旧消息
                    old_summary = pipe.get(summary_key) or ""# 从 Redis 读之前累积的旧摘要
                    new_summary = self._safe_text(f"{old_summary}\n{summary}").strip()# 拼接

                    pipe.multi()# 3.开启事务
                    pipe.ltrim(key, 0, keep_end)# 4. 裁剪列表（排队，等 execute）
                    pipe.expire(key, 86400)# 5. 设置过期时间（排队，等 execute）
                    pipe.setex(summary_key, 86400, new_summary)# 6.写入摘要（排队，等 execute）
                    pipe.execute()# 7. 一次性发送 4、5、6，原子执行（要么全成功，要么全失败）
                    return True
                except redis.exceptions.WatchError:
                    continue
        logger.warning("工作记忆压缩提交冲突次数过多，保留原消息等待下次压缩")
        return False

    async def _search_episodic(self, user_id: str, query: str) -> List[str]:
        """语义检索情景记忆。"""
        query_text = self._safe_text(query).strip()
        if not query_text:
            return []
        try:
            items = self._episodic.search(
                query_text,
                top_k=self.HISTORY_TOP_K,
                expr=user_filter(user_id, "episodic"),#限定只查当前用户的情景记忆。
            )
            return [self._safe_text(item.get("text", "")) for item in items if item.get("text")]
        except Exception as ex:
            logger.warning(f"Milvus 情景记忆检索失败: {ex}")
            return []

    async def _store_episodic(self, user_id: str, conv_id: str, text: str, summary: str) -> None:
        """将压缩后的对话片段存入情景记忆。"""
        try:
            user_id = self._safe_text(user_id)
            conv_id = self._safe_text(conv_id)
            text = self._safe_text(text)
            summary = self._safe_text(summary)
            doc_id = hashlib.md5(f"{user_id}{conv_id}{time.time()}".encode()).hexdigest()#生成文档 ID。
            self._episodic.add_texts([{
                "id": doc_id,
                "text": summary,
                "title": "conversation_summary",
                "user_id": user_id,
                "conv_id": conv_id,
                "kind": "episodic",
                "metadata": {"full_text": self._safe_text(text[:500])},
                "ts": datetime.now().isoformat(),
            }])
        except Exception as ex:
            logger.warning(f"存储情景记忆失败: {ex}")

    async def _get_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像（取最新一条）。"""
        try:
            rows = self._profile.query_by_user(user_id, "profile", limit=10)
            if rows:
                return json.loads(rows[0].get("text") or "{}")
        except Exception:
            pass
        return {}

    @staticmethod
    def _wm_key(user_id: str, conv_id: str) -> str:
        return f"wm:{quote(str(user_id), safe='')}:{quote(str(conv_id), safe='')}"

    @staticmethod
    def _summary_key(user_id: str, conv_id: str) -> str:
        return f"summary:{quote(str(user_id), safe='')}:{quote(str(conv_id), safe='')}"

    @staticmethod
    def _safe_text(value: Any) -> str:
        """转成存储层可接受的普通 UTF-8 字符串。"""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")

    #@classmethod 表示第一个参数是类本身 cls
    @classmethod
    def _safe_metadata_value(cls, value: Any) -> Any:
        """递归清洗 metadata，避免 Redis/向量库后续读写遇到非法 UTF-8。"""
        if isinstance(value, str):
            return cls._safe_text(value)
        if isinstance(value, dict):
            return {cls._safe_text(k): cls._safe_metadata_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._safe_metadata_value(v) for v in value]
        return value
