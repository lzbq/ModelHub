"""Reset the knowledge collection and seed ModelHub documents."""
import json
import os
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modelhub_tools.knowledge_base import KnowledgeBase  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    kb = KnowledgeBase(
        milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530").strip(),
        milvus_token=os.getenv("MILVUS_TOKEN", "").strip() or None,
        milvus_dim=int(os.getenv("EMBEDDING_DIM", os.getenv("MILVUS_DIM", "512"))),
        collection_name=os.getenv("MILVUS_KNOWLEDGE_COLLECTION", "modelhub_knowledge").strip(),
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "sentence_transformers").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip(),
        query_instruction=os.getenv("EMBEDDING_QUERY_INSTRUCTION", "").strip(),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "").strip(),
    )
    added = kb.reset_to_default_docs()
    sample = kb.search("限时 Token 套餐为什么抢不到", top_k=5)
    print(json.dumps({
        "message": "已导入 ModelHub 知识文档",
        "collection": kb.collection_name,
        "added_chunks": added,
        "total_chunks": kb.doc_count(),
        "sample_titles": [item.get("title") for item in sample],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
