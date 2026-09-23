"""
这个文件的功能是：封装一个基于 Milvus 的文本向量存储层。
它主要做三件事：
1.把文本转成向量
默认可通过 stable_text_embedding() 用字符 n-gram + MD5 哈希生成固定长度向量；也可以通过 sentence-transformers 加载中文 embedding 模型，例如 BAAI/bge-small-zh-v1.5。
2.把文本和元数据写入 Milvus
MilvusTextStore.add_texts() 会接收文本、标题、用户 ID、会话 ID、类型、metadata、时间戳等信息，清洗后写入 Milvus collection。写入前会根据相同 id 删除旧数据，实现类似覆盖更新。
3.从 Milvus 中检索文本
search() 会把查询文本也转成向量，然后用 Milvus 的 cosine 相似度搜索最相关的文本片段。
query_by_user() 和 user_filter() 用于按 user_id、kind 查询或过滤数据，比如只搜索某个用户的情景记忆或用户画像。
在项目中的作用是：给知识库 RAG、长期记忆、用户画像这些功能提供统一的向量存储和检索能力。

"""
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)#__name__ 是当前模块名。这样日志能显示来自哪个模块。


class TextEmbedder:
    """文本向量生成器，支持本地哈希向量和 sentence-transformers 中文模型。"""

    _MODEL_CACHE: Dict[Tuple[str, str], Any] = {}

    def __init__(
        self,
        *,
        backend: str = "stable",
        dim: int = 256,
        model_name: str = "",
        query_instruction: str = "",
        device: str = "",
    ):
        self.backend = (backend or "stable").strip().lower().replace("-", "_")
        self.dim = dim
        self.model_name = (model_name or "").strip()
        self.query_instruction = query_instruction or ""
        self.device = (device or "").strip() or None
        self._model = None

        if self.backend in {"stable", "hash", "local"}:
            self.backend = "stable"
            return

        if self.backend in {"sentence_transformers", "sentence_transformer", "bge"}:
            self.backend = "sentence_transformers"
            if not self.model_name:
                raise RuntimeError("使用 sentence-transformers embedding 时必须配置模型名")
            self._model = self._load_sentence_transformer()
            model_dim = self._sentence_transformer_dim()
            if model_dim and model_dim != self.dim:
                raise RuntimeError(
                    f"Embedding 维度不一致: 模型 {self.model_name} 输出 {model_dim} 维，"
                    f"但当前 Milvus collection 配置为 {self.dim} 维。请调整 EMBEDDING_DIM/MILVUS_DIM 并重建向量集合。"
                )
            return

        raise RuntimeError(f"不支持的 embedding backend: {backend}")

    def _load_sentence_transformer(self):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as ex:
            raise RuntimeError(
                "使用中文 embedding 需要安装 sentence-transformers 和 torch，"
                "请先执行: pip install -r requirements.txt"
            ) from ex

        cache_key = (self.model_name, self.device or "")
        if cache_key not in self._MODEL_CACHE:
            kwargs: Dict[str, Any] = {}
            if self.device:
                kwargs["device"] = self.device
            logger.info(f"加载 embedding 模型: {self.model_name} device={self.device or 'auto'}")
            self._MODEL_CACHE[cache_key] = SentenceTransformer(self.model_name, **kwargs)
        return self._MODEL_CACHE[cache_key]

    def _sentence_transformer_dim(self) -> Optional[int]:
        try:
            return int(self._model.get_sentence_embedding_dimension())
        except Exception:
            return None

    def embed(self, text: str, *, is_query: bool = False) -> List[float]:
        if self.backend == "stable":
            return stable_text_embedding(text, self.dim)

        value = _safe_text(text)
        if is_query and self.query_instruction and not value.startswith(self.query_instruction):
            value = f"{self.query_instruction}{value}"

        vector = self._model.encode(
            value,
            normalize_embeddings=True,#开启向量归一化后，两向量内积=余弦相似度
            show_progress_bar=False,
        )
        return [float(x) for x in vector.tolist()]


def stable_text_embedding(text: str, dims: int = 256) -> List[float]:
    """本地embedding函数。它不调用模型，而是用字符 n-gram + 哈希生成向量。"""
    normalized = (text or "").lower().strip()#规范化文本
    vec = [0.0] * dims#创建长度为 dims 的零向量
    tokens = set()
    #生成字符 n-gram：例如 "abc" 会产生：1-gram: a, b, c  2-gram: ab, bc  3-gram: abc
    for n in (1, 2, 3):
        if len(normalized) >= n:
            tokens.update(normalized[i:i + n] for i in range(len(normalized) - n + 1))
    if not tokens:
        tokens.add(normalized)

    for token in tokens:
        #token.encode("utf-8")：字符串转字节。
        #hashlib.md5(...).digest()：得到 16 字节哈希。16进制字符串，16字节=32字符
        digest = hashlib.md5(token.encode("utf-8")).digest()
        #digest[:4]：取前 4 个字节。
        #int.from_bytes(..., "big")：把字节转整数。
        #% dims：映射到向量下标范围内。
        idx = int.from_bytes(digest[:4], "big") % dims
        #sign：用第 5 个字节决定加 +1 还是 -1。
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    #向量归一化
    norm = sum(x * x for x in vec) ** 0.5#计算向量长度。
    return [x / norm for x in vec] if norm else vec#如果向量长度不是 0，就归一化；否则直接返回原向量。

#把任意值转成安全字符串。
def _safe_text(value: Any, max_len: int = 8192) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.encode("utf-8", errors="ignore").decode("utf-8")#清理非法 UTF-8 字符。
    return value[:max_len]#截断到最大长度

#定义 Milvus 查询表达式里的字符串转义函数。
def _expr_value(value: str) -> str:
    return _safe_text(value, 1024).replace("\\", "\\\\").replace('"', '\\"')

#定义一个类，表示“Milvus 文本存储器”。
class MilvusTextStore:
    """
    这个类封装了 Milvus collection。

    Schema:
      id, vector, text, title, user_id, conv_id, kind, metadata, ts,
      chunk_index, total_chunks
    """

    def __init__(
        self,
        collection_name: str,
        uri: str,
        token: Optional[str] = None,
        *,
        alias: Optional[str] = None,#连接别名
        dim: int = 256,
        embedding_backend: str = "stable",
        embedding_model: str = "",
        query_instruction: str = "",
        embedding_device: str = "",
    ):
        try:
            from pymilvus import connections
        except Exception as ex:
            raise RuntimeError("使用 Milvus 需要安装 pymilvus，请确认 requirements.txt 已安装") from ex

        self.collection_name = collection_name
        self.dim = dim
        self._alias = alias or f"echomind_{collection_name}_{int(time.time() * 1000)}"
        self._embedder = TextEmbedder(
            backend=embedding_backend,
            dim=dim,
            model_name=embedding_model,
            query_instruction=query_instruction,
            device=embedding_device,
        )

        kwargs: Dict[str, Any] = {"alias": self._alias, "uri": uri}
        if token:
            kwargs["token"] = token
        connections.connect(**kwargs)
        self._collection = self._ensure_collection()

    def _ensure_collection(self):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

        #创建或打开 collection
        if not utility.has_collection(self.collection_name, using=self._alias):
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="conv_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="kind", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="ts", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
                FieldSchema(name="total_chunks", dtype=DataType.INT64),
            ]
            schema = CollectionSchema(
                fields=fields,
                description=f"text collection: {self.collection_name}",
                enable_dynamic_field=False,#禁止动态字段。也就是说，只能插入 schema 里定义过的字段。
            )
            #真正创建 collection。
            collection = Collection(self.collection_name, schema=schema, using=self._alias)
            #给 vector 字段创建索引。
            collection.create_index(
                field_name="vector",
                index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE", "params": {}},
            )
            logger.info(f"Milvus collection 已创建: {self.collection_name}")
        else:
            collection = Collection(self.collection_name, using=self._alias)
            existing_dim = self._collection_dim(collection)
            if existing_dim and existing_dim != self.dim:
                raise RuntimeError(
                    f"Milvus collection {self.collection_name} 当前是 {existing_dim} 维，"
                    f"但配置需要 {self.dim} 维。请先重建该 collection。"
                )

        collection.load()#把 collection 加载进内存，准备搜索。
        return collection

    @staticmethod
    def _collection_dim(collection) -> Optional[int]:
        """读取已有 collection 的向量维度。"""
        try:
            for field in collection.schema.fields:
                if field.name == "vector":
                    params = getattr(field, "params", {}) or {}
                    value = params.get("dim") or params.get("DIM")
                    return int(value) if value else None
        except Exception:
            return None
        return None

    @property
    def count(self) -> int:
        try:
            return int(self._collection.num_entities)#返回 collection 里的实体数量。
        except Exception:
            return 0

    def clear(self) -> None:
        """清空当前 collection，并按原 schema 重建索引。"""
        from pymilvus import utility

        try:
            self._collection.release()
        except Exception:
            pass

        if utility.has_collection(self.collection_name, using=self._alias):
            utility.drop_collection(self.collection_name, using=self._alias)
            logger.info(f"Milvus collection 已清空: {self.collection_name}")

        self._collection = self._ensure_collection()

    #批量插入文本
    def add_texts(self, items: List[Dict[str, Any]]) -> int:
        if not items:
            return 0

        rows = []
        for item in items:
            text = _safe_text(item.get("text") or item.get("content"))
            if not text.strip():
                continue
            metadata = item.get("metadata", {})
            if not isinstance(metadata, str):
                metadata = json.dumps(metadata, ensure_ascii=False)
            rows.append({
                "id": _safe_text(item["id"], 64),
                "vector": self._embedder.embed(text, is_query=False),
                "text": text,
                "title": _safe_text(item.get("title", ""), 512),
                "user_id": _safe_text(item.get("user_id", ""), 256),
                "conv_id": _safe_text(item.get("conv_id", ""), 256),#会话 ID。
                "kind": _safe_text(item.get("kind", ""), 64),#数据类型。
                "metadata": _safe_text(metadata, 4096),
                "ts": _safe_text(item.get("ts", ""), 64),
                "chunk_index": int(item.get("chunk_index", 0)),
                "total_chunks": int(item.get("total_chunks", 1)),#总分片数，默认 1。
            })

        if not rows:
            return 0

        ids = [r["id"] for r in rows]
        try:
            #插入前先删除同 ID 的旧记录，相当于覆盖。
            self._collection.delete(f'id in ["' + '","'.join(_expr_value(i) for i in ids) + '"]')
        except Exception:
            pass

        self._collection.insert([
            [r["id"] for r in rows],
            [r["vector"] for r in rows],
            [r["text"] for r in rows],
            [r["title"] for r in rows],
            [r["user_id"] for r in rows],
            [r["conv_id"] for r in rows],
            [r["kind"] for r in rows],
            [r["metadata"] for r in rows],
            [r["ts"] for r in rows],
            [r["chunk_index"] for r in rows],
            [r["total_chunks"] for r in rows],
        ])
        self._collection.flush()#把数据刷新到 Milvus。
        return len(rows)
    #搜索文本相似内容。
    def search(self, query: str, top_k: int = 5, expr: Optional[str] = None) -> List[Dict[str, Any]]:
        if not (query or "").strip():
            return []
        results = self._collection.search(#调用 Milvus 做向量搜索。
            data=[self._embedder.embed(query, is_query=True)],
            anns_field="vector",#告诉 Milvus 在 vector 字段上搜索。
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr,#附加过滤条件。
            output_fields=["text", "title", "user_id", "conv_id", "kind", "metadata", "ts", "chunk_index", "total_chunks"],
        )

        items: List[Dict[str, Any]] = []
        for hit in results[0]:
            entity = hit.entity
            metadata_raw = entity.get("metadata") or "{}"
            try:
                metadata = json.loads(metadata_raw)#把 JSON 字符串转回字典。
            except Exception:
                metadata = {}
            items.append({
                "id": hit.id,
                "text": entity.get("text") or "",
                "title": entity.get("title") or "",
                "user_id": entity.get("user_id") or "",
                "conv_id": entity.get("conv_id") or "",
                "kind": entity.get("kind") or "",
                "metadata": metadata,
                "ts": entity.get("ts") or "",
                "chunk_index": entity.get("chunk_index") or 0,
                "total_chunks": entity.get("total_chunks") or 1,
                "score": round(float(hit.score), 4),
            })
        return items

    #按用户和类型查询，不做向量相似搜索。
    def query_by_user(self, user_id: str, kind: str, limit: int = 10) -> List[Dict[str, Any]]:
        #拼 Milvus 查询表达式。
        expr = f'user_id == "{_expr_value(user_id)}" and kind == "{_expr_value(kind)}"'
        try:
            rows = self._collection.query(
                expr=expr,
                output_fields=["id", "text", "title", "metadata", "ts", "conv_id"],
                limit=limit,
            )
        except Exception:
            return []
        return sorted(rows, key=lambda r: r.get("ts", ""), reverse=True)#按时间戳 ts 倒序排列，最新的在前。

#定义一个辅助函数，专门生成用户过滤条件。
def user_filter(user_id: str, kind: str) -> str:
    return f'user_id == "{_expr_value(user_id)}" and kind == "{_expr_value(kind)}"'
