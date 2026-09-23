"""
RAG 知识库 —— 基于 Milvus 的真实检索实现。

功能：
  1. 文档导入：将文本切片后存入向量库
  2. 语义检索：根据 query 从知识库中检索最相关的文档片段
  3. 与 MCP 工具框架集成：作为 knowledge_search 工具的真实 handler

默认连接已有 Milvus，向量生成方式由 EMBEDDING_BACKEND/EMBEDDING_MODEL 配置决定。
当前 ModelHub 版本通常使用 BAAI/bge-small-zh-v1.5 中文 embedding。
"""
import asyncio
import hashlib
import json
import logging
import pathlib
from typing import Any, Dict, List, Optional

from storage.vector_store import MilvusTextStore

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
    基于向量数据库的 RAG 知识库。

    具体 embedding 后端交给 MilvusTextStore 统一处理：
    - sentence_transformers/bge: 中文语义向量
    - stable/hash: 本地字符哈希兜底
    """

    COLLECTION_NAME = "knowledge_base"
    DEFAULT_DOCS_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "knowledge" / "modelhub_seed.json"

    def __init__(
        self,
        milvus_uri: str = "http://localhost:19530",
        milvus_token: Optional[str] = None,
        milvus_dim: int = 256,
        collection_name: Optional[str] = None,
        embedding_backend: str = "stable",
        embedding_model: str = "",
        query_instruction: str = "",
        embedding_device: str = "",
    ):
        self.collection_name = collection_name or self.COLLECTION_NAME
        #创建底层 Milvus 文本存储对象
        self._milvus = MilvusTextStore(
            collection_name=self.collection_name,
            uri=milvus_uri,
            token=milvus_token,
            dim=milvus_dim,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            query_instruction=query_instruction,
            embedding_device=embedding_device,
        )
        logger.info(f"知识库 Milvus 已连接: {milvus_uri} / {self.collection_name}")

        # 如果当前 collection 里没有文档片段，就导入 ModelHub 默认知识。
        #注意：这个判断意味着服务第一次启动、Milvus collection 为空时，会自动写入默认业务知识。
        if self._milvus.count == 0:
            self._load_default_docs()

    # ── 文档管理 ──────────────────────────────────────────────────────────────

    def add_documents(self, documents: List[Dict[str, Any]]) -> int:
        """
        批量导入文档到知识库。

        documents 格式: [{"title": "...", "content": "..."}, ...]
        长文档会自动切片（每片 500 字）。
        """
        #先准备一个空列表，用来收集要写入 Milvus 的片段数据。
        rows = []

        for doc in documents:
            title   = doc.get("title", "")
            content = doc.get("content", "")
            chunks  = self._chunk_text(content, chunk_size=500)
            metadata = self._doc_metadata(doc)

            for i, chunk in enumerate(chunks):
                #hashlib.md5(...).hexdigest()：生成 MD5 十六进制摘要。
                doc_id = hashlib.md5(f"{title}_{i}_{chunk[:50]}".encode()).hexdigest()
                rows.append({
                    "id": doc_id,
                    "text": chunk,
                    "title": title,
                    "kind": "knowledge",#表示这是知识库数据
                    "metadata": metadata,
                    "chunk_index": i,#当前是第几个片段。
                    "total_chunks": len(chunks),#这篇文档总共切成多少片。
                })
        #把所有片段交给 MilvusTextStore.add_texts() 写入 Milvus，并返回实际写入数量。
        count = self._milvus.add_texts(rows)
        logger.info(f"知识库导入 {count} 个 Milvus 文档片段")
        return count

    def clear(self) -> None:
        """清空当前知识库 collection。"""
        self._milvus.clear()

    def reset_to_default_docs(self) -> int:
        """清空旧知识库，并重新导入 ModelHub 默认文档。"""
        self.clear()
        return self._load_default_docs()

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        语义检索：根据 query 返回最相关的文档片段。

        使用 Milvus 的向量相似度召回。当前已接入中文 embedding，不再叠加关键词/分类分。
        """
        results = []
        for item in self._milvus.search(query, top_k=top_k):
            title = item.get("title", "")
            content = item.get("text", "")
            metadata = item.get("metadata") or {}
            results.append({
                "title": title,
                "content": content,
                "score": item.get("score", 0.0),
                "category": metadata.get("category", ""),
                "tags": metadata.get("tags", []),
                "chunk": item.get("chunk_index", 0),
            })
        return results

    @property  #把方法伪装成属性使用
    def doc_count(self) -> int:
        #返回 Milvus collection 当前的实体数量，也就是文档片段数。
        return self._milvus.count

    # ── MCP 工具 handler ─────────────────────────────────────────────────────

    async def search_handler(self, params: Dict[str, Any], context: Any) -> List[Dict]:
        """
        作为 MCP 工具的 handler 注册。

        MCPToolManager.register(Tool(
            name="knowledge_search",
            handler=kb.search_handler,
            ...
        ))
        """
        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        return await asyncio.to_thread(self.search, query, top_k=top_k)

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        """将长文本按 chunk_size 切片，保留语义完整性（按句号/换行切分）。"""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        current = ""
        # 按句子切分
        sentences = text.replace("\n", "。").split("。")
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > chunk_size:
                if current:
                    chunks.append(current)
                current = sent
            else:
                current = f"{current}。{sent}" if current else sent

        if current:
            chunks.append(current)

        return chunks

    @classmethod
    def _doc_metadata(cls, doc: Dict[str, Any]) -> Dict[str, Any]:
        """标准化知识文档元数据。"""
        metadata = doc.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        category = str(doc.get("category") or metadata.get("category") or "general").strip()

        raw_tags = doc.get("tags") or metadata.get("tags") or []
        if not isinstance(raw_tags, list):
            raw_tags = []
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]

        return {
            **metadata,
            "category": category,
            "tags": tags,
        }

    def _load_seed_docs(self) -> List[Dict[str, Any]]:
        """从 data/knowledge 读取 ModelHub 种子文档。"""
        if not self.DEFAULT_DOCS_PATH.exists():
            return []
        try:
            docs = json.loads(self.DEFAULT_DOCS_PATH.read_text(encoding="utf-8"))
        except Exception as ex:
            logger.warning(f"读取默认知识库文档失败: {ex}")
            return []
        if not isinstance(docs, list):
            logger.warning("默认知识库文档格式错误，应为 JSON 数组")
            return []
        return [
            {
                "title": str(doc.get("title", "")),
                "content": str(doc.get("content", "")),
                "category": doc.get("category", ""),
                "tags": doc.get("tags", []),
            }
            for doc in docs
            if isinstance(doc, dict) and doc.get("title") and doc.get("content")
        ]

    def _load_default_docs(self) -> int:
        """导入 ModelHub 默认知识库文档。"""
        seed_docs = self._load_seed_docs()
        if seed_docs:
            count = self.add_documents(seed_docs)
            logger.info(f"已导入 ModelHub 默认知识库: {len(seed_docs)} 篇文档 / {count} 个片段")
            return count

        default_docs = [{
            "title": "ModelHub 默认安全边界",
            "content": (
                "Agent 只负责模型选型、成本估算、套餐订单查询和 API 排查。"
                "抢购、支付、退款、额度调整和 API Key 操作必须由 Java 后端在用户确认后执行。"
            ),
        }]
        count = self.add_documents(default_docs)
        logger.info(f"已导入默认知识库: {len(default_docs)} 篇文档")
        return count

