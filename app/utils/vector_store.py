"""ChromaDB 向量数据库初始化

在应用启动时加载 Embedding 模型并初始化向量库。

多进程并发写保护：
- ChromaDB PersistentClient 底层用 SQLite 存储，多个 Gunicorn worker 进程同时写
  同一持久化目录会触发 SQLite 写锁冲突（database is locked）导致 500。
- 写操作（add/delete）统一通过 _with_write_lock 获取跨进程文件锁串行化，
  并带短重试兜底，避免瞬时锁冲突。
- 读操作（search）不需要锁。
"""
import os
import time
import logging
from chromadb import PersistentClient
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Global instances
_vector_collection = None
_embedding_model = None
_LOCK_FILE = None  # 跨进程写锁文件路径（init 时设置）
_WRITE_RETRIES = 5
_WRITE_RETRY_DELAY = 0.2


def _get_lock_file() -> str:
    """获取跨进程写锁文件路径（与持久化目录同级）"""
    global _LOCK_FILE
    if _LOCK_FILE is None:
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", "")
        if not persist_dir:
            import app.config as _cfg
            persist_dir = _cfg.Config.CHROMA_PERSIST_DIR
        _LOCK_FILE = os.path.join(persist_dir, ".write.lock")
    return _LOCK_FILE


def _with_write_lock(fn, *args, **kwargs):
    """跨进程文件锁包裹写操作（fcntl 仅 Unix；Windows 环境退化为直接执行）

    多个 worker 写同一个 SQLite 文件时串行化，避免 database is locked。
    """
    try:
        import fcntl  # Unix
    except ImportError:
        fcntl = None  # Windows 等环境

    lock_path = _get_lock_file()
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    # 重试几次，兜底瞬时锁冲突
    last_err = None
    for attempt in range(_WRITE_RETRIES):
        try:
            if fcntl is None:
                return fn(*args, **kwargs)
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    return fn(*args, **kwargs)
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except Exception as e:
            last_err = e
            if "locked" in str(e).lower() or "database is locked" in str(e).lower():
                time.sleep(_WRITE_RETRY_DELAY * (attempt + 1))
                continue
            raise
    raise last_err


def init_vector_store(persist_dir: str, model_name: str = "BAAI/bge-small-zh"):
    """初始化向量数据库和 Embedding 模型

    Args:
        persist_dir: ChromaDB 持久化目录
        model_name: Embedding 模型名称
    """
    global _vector_collection, _embedding_model, _LOCK_FILE

    # 确保持久化目录存在（含写锁目录）
    os.makedirs(persist_dir, exist_ok=True)
    _LOCK_FILE = os.path.join(persist_dir, ".write.lock")

    # 初始化 ChromaDB 客户端
    client = PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    # 创建或获取集合
    _vector_collection = client.get_or_create_collection(
        name="knowledge",
        metadata={"hnsw:space": "cosine"},  # 使用余弦相似度
    )

    # 加载 Embedding 模型
    logger.info(f"Loading embedding model: {model_name}")
    _embedding_model = SentenceTransformer(model_name)
    logger.info("Embedding model loaded successfully.")

    total = _vector_collection.count()
    logger.info(f"Vector store initialized. Existing chunks: {total}")

    return _vector_collection, _embedding_model


def get_vector_collection():
    """获取向量数据库集合实例"""
    return _vector_collection


def get_embedding_model():
    """获取 Embedding 模型实例"""
    return _embedding_model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """将文本列表转换为向量"""
    if _embedding_model is None:
        raise RuntimeError("Embedding model not initialized. Call init_vector_store first.")
    return _embedding_model.encode(texts).tolist()


def search_knowledge(query: str, top_k: int = 5, threshold: float = 0.6) -> list[dict]:
    """在知识库中搜索与查询最相似的片段

    Args:
        query: 用户问题
        top_k: 返回 Top-K 个结果
        threshold: 相似度阈值，低于此值不返回

    Returns:
        list[dict]: 包含 document、metadata、similarity 的列表
    """
    if _vector_collection is None:
        raise RuntimeError("Vector store not initialized.")

    # 向量化查询
    query_embedding = embed_texts([query])[0]

    # 搜索
    results = _vector_collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    # 整理结果
    hits = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            similarity = 1 - results["distances"][0][i]  # cosine distance → similarity
            if similarity >= threshold:
                hits.append({
                    "document": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "similarity": round(similarity, 4),
                })

    return hits


def add_knowledge(doc_id: str, text: str, metadata: dict = None):
    """添加一条知识到向量库

    Args:
        doc_id: 知识 ID（对应 MySQL knowledge 表 id）
        text: 知识内容
        metadata: 元数据（标题、来源、标签等）
    """
    if _vector_collection is None:
        raise RuntimeError("Vector store not initialized.")

    def _do_add():
        embedding = embed_texts([text])[0]
        _vector_collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata or {}],
        )

    _with_write_lock(_do_add)


def delete_knowledge(doc_id: str):
    """从向量库中删除知识"""
    if _vector_collection is None:
        raise RuntimeError("Vector store not initialized.")

    def _do_delete():
        _vector_collection.delete(ids=[doc_id])

    _with_write_lock(_do_delete)


def delete_knowledge_chunks(knowledge_id: int, max_chunks: int = 1000):
    """安全删除某条知识的所有切片（只删除实际存在的，不删除不存在的）

    Args:
        knowledge_id: 知识 ID（对应 MySQL knowledge 表 id）
        max_chunks: 最大预期切片数（安全上限）
    """
    def _do_delete_chunks():
        candidate_ids = [f"{knowledge_id}_{i}" for i in range(max_chunks)]
        # 查询实际存在的 ID
        existing = _vector_collection.get(ids=candidate_ids)
        if existing and existing["ids"]:
            _vector_collection.delete(ids=existing["ids"])
            logger.info(f"已删除知识 {knowledge_id} 的 {len(existing['ids'])} 个旧切片")
            return len(existing["ids"])
        return 0

    return _with_write_lock(_do_delete_chunks)


def update_knowledge(doc_id: str, text: str, metadata: dict = None):
    """更新向量库中的知识（先删后加）"""
    delete_knowledge(doc_id)
    add_knowledge(doc_id, text, metadata)
