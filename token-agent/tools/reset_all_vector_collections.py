"""Drop and rebuild all EchoMind Milvus vector collections for the configured embedding model."""
import json
import os
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modelhub_tools.knowledge_base import KnowledgeBase  # noqa: E402
from storage.vector_store import MilvusTextStore, TextEmbedder  # noqa: E402


def _drop_collection(name: str, uri: str, token: str | None) -> None:
    from pymilvus import connections, utility

    alias = f"reset_{name}"
    kwargs = {"alias": alias, "uri": uri}
    if token:
        kwargs["token"] = token
    connections.connect(**kwargs)
    if utility.has_collection(name, using=alias):
        utility.drop_collection(name, using=alias)
        print(f"dropped: {name}")
    connections.disconnect(alias)


def main() -> None:
    load_dotenv(ROOT / ".env")

    uri = os.getenv("MILVUS_URI", "http://localhost:19530").strip()
    token = os.getenv("MILVUS_TOKEN", "").strip() or None
    dim = int(os.getenv("EMBEDDING_DIM", os.getenv("MILVUS_DIM", "512")))
    backend = os.getenv("EMBEDDING_BACKEND", "sentence_transformers").strip()
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip()
    query_instruction = os.getenv("EMBEDDING_QUERY_INSTRUCTION", "").strip()
    device = os.getenv("EMBEDDING_DEVICE", "").strip()

    knowledge_collection = os.getenv("MILVUS_KNOWLEDGE_COLLECTION", "echomind_knowledge").strip()
    episodic_collection = os.getenv("MILVUS_EPISODIC_COLLECTION", "echomind_episodic").strip()
    profile_collection = os.getenv("MILVUS_PROFILE_COLLECTION", "echomind_user_profile").strip()

    # Load and validate the embedding model before dropping any collection. This avoids
    # deleting existing vectors when the model cannot be downloaded or loaded.
    embedder = TextEmbedder(
        backend=backend,
        dim=dim,
        model_name=model,
        query_instruction=query_instruction,
        device=device,
    )
    embedder.embed("模型加载预检", is_query=True)
    print(f"embedding model ready: {model} dim={dim}")

    for name in (knowledge_collection, episodic_collection, profile_collection):
        _drop_collection(name, uri, token)

    kb = KnowledgeBase(
        milvus_uri=uri,
        milvus_token=token,
        milvus_dim=dim,
        collection_name=knowledge_collection,
        embedding_backend=backend,
        embedding_model=model,
        query_instruction=query_instruction,
        embedding_device=device,
    )
    added = kb.reset_to_default_docs()

    MilvusTextStore(
        collection_name=episodic_collection,
        uri=uri,
        token=token,
        dim=dim,
        embedding_backend=backend,
        embedding_model=model,
        query_instruction=query_instruction,
        embedding_device=device,
    )
    MilvusTextStore(
        collection_name=profile_collection,
        uri=uri,
        token=token,
        dim=dim,
        embedding_backend=backend,
        embedding_model=model,
        query_instruction=query_instruction,
        embedding_device=device,
    )

    sample = kb.search("秒杀券为什么抢不到", top_k=5)
    print(json.dumps({
        "message": "已重建知识库、情景记忆、用户画像三个向量集合",
        "embedding_backend": backend,
        "embedding_model": model,
        "embedding_dim": dim,
        "collections": {
            "knowledge": knowledge_collection,
            "episodic": episodic_collection,
            "profile": profile_collection,
        },
        "knowledge_added_chunks": added,
        "sample_titles": [item.get("title") for item in sample],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
