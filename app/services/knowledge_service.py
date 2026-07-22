"""知识库服务 - 知识管理

负责知识的增删改查、切片、向量化同步。
"""
import logging
from datetime import datetime
from app.models.models import db, Knowledge
from app.utils.vector_store import add_knowledge, delete_knowledge, update_knowledge, search_knowledge

logger = logging.getLogger(__name__)


class KnowledgeService:
    """知识库服务"""

    @staticmethod
    def add(title: str, content: str, source: str = "manual", tags: str = None) -> int:
        """新增知识（同时存入 MySQL 和 ChromaDB）

        Returns:
            int: 知识 ID
        """
        # 1. 存入 MySQL
        knowledge = Knowledge(
            title=title,
            content=content,
            source=source,
            tags=tags,
        )
        db.session.add(knowledge)
        db.session.commit()

        # 2. 切片
        chunks = _chunk_text(content)

        # 3. 向量化后存入 ChromaDB
        for i, chunk in enumerate(chunks):
            chunk_id = f"{knowledge.id}_{i}"
            metadata = {
                "title": title,
                "source": source or "",
                "tags": tags or "",
                "chunk_index": i,
            }
            add_knowledge(chunk_id, chunk, metadata)

        logger.info(f"知识已添加: id={knowledge.id}, title={title}, chunks={len(chunks)}")
        return knowledge.id

    @staticmethod
    def update(knowledge_id: int, title: str = None, content: str = None,
               tags: str = None) -> bool:
        """更新知识"""
        knowledge = Knowledge.query.get(knowledge_id)
        if not knowledge:
            logger.warning(f"知识不存在: id={knowledge_id}")
            return False

        if title:
            knowledge.title = title
        if content:
            knowledge.content = content
        if tags is not None:
            knowledge.tags = tags
        knowledge.updated_at = datetime.utcnow()
        db.session.commit()

        # 如果内容变了，重做向量库中的切片
        if content:
            # 删除旧切片
            chunks_before = KnowledgeService.get_chunk_count(knowledge_id)
            for i in range(chunks_before):
                delete_knowledge(f"{knowledge_id}_{i}")

            # 切片后重新存入
            chunks = _chunk_text(content)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{knowledge_id}_{i}"
                metadata = {
                    "title": knowledge.title,
                    "source": knowledge.source or "",
                    "tags": knowledge.tags or "",
                    "chunk_index": i,
                }
                add_knowledge(chunk_id, chunk, metadata)

        logger.info(f"知识已更新: id={knowledge_id}")
        return True

    @staticmethod
    def delete(knowledge_id: int) -> bool:
        """删除知识"""
        knowledge = Knowledge.query.get(knowledge_id)
        if not knowledge:
            return False

        # 删除向量库中的切片
        chunks_before = KnowledgeService.get_chunk_count(knowledge_id)
        for i in range(chunks_before):
            delete_knowledge(f"{knowledge_id}_{i}")

        db.session.delete(knowledge)
        db.session.commit()
        logger.info(f"知识已删除: id={knowledge_id}")
        return True

    @staticmethod
    def get_chunk_count(knowledge_id: int) -> int:
        """估算知识的切片数量（按500字一块估算）"""
        knowledge = Knowledge.query.get(knowledge_id)
        if not knowledge or not knowledge.content:
            return 0
        return max(1, (len(knowledge.content) + 250) // 500)

    @staticmethod
    def search(query: str, top_k: int = 5) -> list[dict]:
        """搜索知识库"""
        return search_knowledge(query, top_k=top_k)

    @staticmethod
    def list_all(page: int = 1, per_page: int = 20) -> tuple:
        """获取知识列表（分页）

        Returns:
            tuple: (知识列表, 总条数)
        """
        pagination = Knowledge.query.order_by(
            Knowledge.updated_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total


def _chunk_text(text: str, max_chunk_size: int = 500) -> list[str]:
    """将文本切分为知识块

    策略：
    1. 优先按空行/段落切分
    2. 如果段落仍太长，按句号切分
    3. 每个 chunk 不超过 max_chunk_size 字
    """
    if not text:
        return []

    # 先按空行切分（段落）
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    for para in paragraphs:
        if len(para) <= max_chunk_size:
            chunks.append(para)
        else:
            # 过长的段落按句号切分
            sentences = para.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
            current = ""
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(current) + len(sent) < max_chunk_size:
                    current += sent
                else:
                    if current:
                        chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)

    return chunks
