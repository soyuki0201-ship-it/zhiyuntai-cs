"""知识库服务 - 知识管理

负责知识的增删改查、切片、向量化同步。
"""
import logging
from datetime import datetime
from app.models.models import db, Knowledge
from app.utils.vector_store import add_knowledge, delete_knowledge_chunks, search_knowledge

logger = logging.getLogger(__name__)


class KnowledgeService:
    """知识库服务"""

    @staticmethod
    def add(title: str, content: str, source: str = "manual", tags: str = None, category: str = None) -> int:
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
            category=category,
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
                "category": category or "",
                "chunk_index": i,
            }
            add_knowledge(chunk_id, chunk, metadata)

        logger.info(f"知识已添加: id={knowledge.id}, title={title}, chunks={len(chunks)}")
        return knowledge.id

    @staticmethod
    def update(knowledge_id: int, title: str = None, content: str = None,
               tags: str = None, category: str = None) -> bool:
        """更新知识"""
        knowledge = Knowledge.query.get(knowledge_id)
        if not knowledge:
            logger.warning(f"知识不存在: id={knowledge_id}")
            return False

        # 删除 ChromaDB 中该知识的所有旧切片
        delete_knowledge_chunks(knowledge_id)

        if title:
            knowledge.title = title
        if content:
            knowledge.content = content
        if tags is not None:
            knowledge.tags = tags
        if category is not None:
            knowledge.category = category
        knowledge.updated_at = datetime.utcnow()
        db.session.commit()

        # 如果内容变了，重新切片并存入
        if content:
            chunks = _chunk_text(content)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{knowledge_id}_{i}"
                metadata = {
                    "title": knowledge.title,
                    "source": knowledge.source or "",
                    "tags": knowledge.tags or "",
                    "category": knowledge.category or "",
                    "chunk_index": i,
                }
                add_knowledge(chunk_id, chunk, metadata)
            logger.info(f"知识已更新: id={knowledge_id}, new_chunks={len(chunks)}")

        return True

    @staticmethod
    def delete(knowledge_id: int) -> bool:
        """删除知识"""
        knowledge = Knowledge.query.get(knowledge_id)
        if not knowledge:
            return False

        # 删除 ChromaDB 中该知识的所有切片
        delete_knowledge_chunks(knowledge_id)

        db.session.delete(knowledge)
        db.session.commit()
        logger.info(f"知识已删除: id={knowledge_id}")
        return True

    @staticmethod
    def search(query: str, top_k: int = None) -> list[dict]:
        """搜索知识库（优先从 AIConfig 读取 top_k 和 threshold）"""
        if top_k is None:
            try:
                from app.models.models import AIConfig
                cfg = AIConfig.query.first()
                top_k = cfg.rag_top_k if cfg else 5
            except Exception:
                top_k = 5
        try:
            from app.models.models import AIConfig
            cfg = AIConfig.query.first()
            threshold = cfg.rag_similarity_threshold if cfg else 0.6
        except Exception:
            threshold = 0.6
        return search_knowledge(query, top_k=top_k, threshold=threshold)

    @staticmethod
    def search_by_title(query: str, page: int = 1, per_page: int = 20) -> tuple:
        """按标题搜索知识条目（支持分页）

        Returns:
            tuple: (知识列表, 总条数, pagination对象)
        """
        query_obj = Knowledge.query
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            query_obj = query_obj.filter(Knowledge.title.like(pattern))
        pagination = query_obj.order_by(Knowledge.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total, pagination

    @staticmethod
    def list_all(page: int = 1, per_page: int = 20) -> tuple:
        """获取知识列表（分页）

        Returns:
            tuple: (知识列表, 总条数, pagination对象)
        """
        pagination = Knowledge.query.order_by(
            Knowledge.updated_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total, pagination


def _chunk_text(text: str, max_chunk_size: int = 500) -> list[str]:
    """将文本切分为适合向量检索的知识块

    切片优先级（语义优先，长度仅作兜底）：
    1. 先按 Markdown 标题层级（#/##/###/####）切分
    2. 同一标题路径下的内容作为一组处理
    3. 同一组内先按空行（\n\n）分段落，段落内保持完整
    4. 同一标题下的短段落（<50字）合并
    5. 无标题时每个独立段落各自成 chunk
    6. 超长段落按句子切分，不在句子中间截断
    """
    import re
    if not text or not text.strip():
        return []

    chunks = []
    # 标题栈：维护当前所处的标题层级链
    title_stack = [""] * 5

    def _get_title_level(line: str) -> int:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            return 0
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break
        return level if 1 <= level <= 4 else 0

    def _build_title_path() -> str:
        parts = [t for t in title_stack if t]
        return "\n".join(parts) if parts else ""

    def _make_chunk(body: str) -> str:
        prefix = _build_title_path()
        body = body.strip()
        if prefix and body:
            return prefix + "\n" + body
        return body

    def _chunk_paragraph(para: str) -> list[str]:
        """将一个段落切分成不超过 max_chunk_size 的块"""
        if len(para) <= max_chunk_size:
            return [para]
        sentences = re.split(r'(?<=[。！？\n])\s*', para)
        sentences = [s.strip() for s in sentences if s.strip()]
        result, cur = [], ""
        for sent in sentences:
            if len(cur) + len(sent) < max_chunk_size:
                cur += sent
            else:
                if cur:
                    result.append(cur)
                cur = sent
        if cur:
            result.append(cur)
        return result

    # 第一步：逐行扫描，按标题分组
    # sections: list of (title_path, [paragraphs])
    current_section_paras = []
    section_title_exists = False  # 当前 section 是否有标题

    def flush_section():
        nonlocal current_section_paras, section_title_exists
        if not current_section_paras:
            return
        body = "\n".join(current_section_paras).strip()
        if not body:
            current_section_paras = []
            section_title_exists = False
            return

        if section_title_exists:
            # 有标题上下文：同一标题下的短段落合并
            lines = body.split("\n")
            merged_paras = []
            buffer = ""
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    if buffer:
                        merged_paras.append(buffer)
                        buffer = ""
                    continue
                if len(stripped) < 50 and buffer:
                    # 短段落，与上一个合并
                    buffer += stripped
                else:
                    if buffer:
                        merged_paras.append(buffer)
                    buffer = stripped
            if buffer:
                merged_paras.append(buffer)

            for para in merged_paras:
                full_chunk = _make_chunk(para)
                chunks.append(full_chunk)
        else:
            # 无标题上下文：按空行切分，无空行的连续行合并为同一段
            groups = [[]]
            for line in body.split("\n"):
                s = line.strip()
                if s:
                    groups[-1].append(s)
                else:
                    if groups[-1]:
                        groups.append([])
            for group in groups:
                text = "".join(group).strip()
                if text:
                    chunks.append(text)

        current_section_paras = []
        section_title_exists = False

    for line in text.split("\n"):
        stripped = line.strip()
        level = _get_title_level(line)

        if level > 0:
            # 遇到标题：刷新上一节
            flush_section()
            # 更新标题栈
            for j in range(level, 5):
                title_stack[j] = ""
            title_stack[level] = stripped.lstrip("#").strip()
            section_title_exists = True
            continue

        # 非标题行
        if stripped:
            current_section_paras.append(stripped)
        else:
            # 空行：段落分隔符
            if current_section_paras:
                current_section_paras.append("")

    # 刷新最后一节
    flush_section()

    # 第二步：对每个 chunk 检查是否超长，超长则按句子切分
    final_chunks = []
    for chunk in chunks:
        lines_in_chunk = chunk.split("\n")
        title_lines = [c for c in lines_in_chunk if c.startswith("#")]
        body_lines = [c for c in lines_in_chunk if not c.startswith("#")]
        body_text = "\n".join(body_lines).strip()
        title_prefix = "\n".join(title_lines)
        if title_prefix:
            title_prefix += "\n"

        if len(body_text) <= max_chunk_size:
            final_chunks.append(chunk)
        else:
            for part in _chunk_paragraph(body_text):
                final_chunks.append(title_prefix + part)

    return final_chunks
