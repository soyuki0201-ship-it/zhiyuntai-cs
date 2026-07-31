"""对话服务（平台无关版）

接收 UnifiedMessage，处理 AI 对话，产出 UnifiedReply。
平台接入层 -> UnifiedMessage -> 此模块 -> UnifiedReply -> 平台发送层

事务管理策略：
- _save_message 使用 flush() 而非 commit()，由顶层调用者统一 commit()
- _handle_ai_response 内部所有操作在同一个事务中完成
- 异常时全局 rollback，避免部分写入
"""
import logging
from datetime import datetime
from flask import current_app
from app.models.models import db, Conversation, Message
from app.core.platform_interface import UnifiedMessage, UnifiedReply
from app.core.platform_manager import get_platform
from app.services.ai_service import AIService
from app.services.knowledge_service import KnowledgeService
from app.services.prompt_builder import PromptBuilder
from app.services.handoff_service import HandoffService

logger = logging.getLogger(__name__)
_ai_service: AIService | None = None


def _get_ai_service():
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService(current_app)
    return _ai_service


def process_unified_message(message: UnifiedMessage):
    """处理统一消息（外部入口）

    管理顶层事务：所有数据库操作在同一事务中完成。
    后续发送：commit成功后执行外部API调用，避免发送成功但回滚的状态不一致。
    """
    pending_reply = None  # 待发送的回复（commit成功后执行）
    try:
        conversation = _get_or_create_conversation(
            user_id=message.user_id, user_name=message.user_name,
            group_id=message.group_id, group_name=message.group_name,
            platform=message.platform,
            platform_config_id=message.platform_config_id,
        )
        if HandoffService.is_handed_over(message.user_id):
            HandoffService.update_last_active(message.user_id)
            _save_message(conversation.id, "user", message.content, message.msg_type, message.platform, message.image_path)
        else:
            _save_message(conversation.id, "user", message.content, message.msg_type, message.platform, message.image_path)
            pending_reply = _handle_ai_response(conversation, message)

        # 所有数据库操作成功，统一提交
        db.session.commit()

        # commit 成功后发送回复（外部位幂等操作，失败不影响数据库一致性）
        if pending_reply is not None:
            _send_reply(pending_reply)

    except Exception as e:
        db.session.rollback()
        logger.error(f"处理消息异常，事务已回滚: {e}", exc_info=True)


def _get_or_create_conversation(user_id: str, user_name: str, group_id: str | None, group_name: str | None, platform: str, platform_config_id: int | None = None) -> Conversation:
    """查找或创建对话记录"""
    try:
        if group_id:
            conv = Conversation.query.filter_by(group_id=group_id, user_id=user_id, status="active").first()
        else:
            conv = Conversation.query.filter_by(user_id=user_id, status="active").first()
        if conv:
            if user_name:
                conv.user_name = user_name
            if group_name:
                conv.group_name = group_name
            if platform_config_id is not None:
                conv.platform_config_id = platform_config_id
            conv.updated_at = datetime.utcnow()
            return conv
        conv = Conversation(channel=platform, user_id=user_id, user_name=user_name,
                            group_id=group_id, group_name=group_name, status="active",
                            platform_config_id=platform_config_id)
        db.session.add(conv)
        return conv
    except Exception as e:
        db.session.rollback()
        logger.error(f"获取/创建对话失败: {e}", exc_info=True)
        raise


def _handle_ai_response(conversation: Conversation, message: UnifiedMessage) -> UnifiedReply | None:
    """处理 AI 回复（与外部调用者共享同一事务）

    职责编排：
    1. 构建检索上下文（历史 + RAG 知识）
    2. 调用 AI 生成回复
    3. 判断转人工 / 自动回复

    注意：不在此方法内 commit()。由 process_unified_message 统一 commit。
    返回待发送的 UnifiedReply（commit 成功后执行发送），转人工时返回 None。

    Returns:
        UnifiedReply | None: commit 后需要发送的回复，None 表示已转人工无需发送
    """
    try:
        content = message.content.strip()
        history = get_conversation_history(conversation.id)
        knowledge_chunks = _retrieve_knowledge(content, history)
        reply = _generate_ai_reply(content, history, knowledge_chunks, message.user_id)

        if PromptBuilder.check_should_handoff(reply):
            # 转人工：保存回复 + 创建接管记录 + 标记对话状态
            _save_message(conversation.id, "assistant", reply, "text", message.platform)
            HandoffService.take_over(message.user_id, is_auto=True)
            conversation.status = "transferred"
            return None  # 转人工，不自动回复
        else:
            # 自动回复：保存回复并返回统一回复模型，由外层 commit 成功后发送
            _save_message(conversation.id, "assistant", reply, "text", message.platform)
            return UnifiedReply(
                platform=message.platform,
                user_id=message.user_id,
                group_id=message.group_id,
                content=reply,
            )
    except Exception as e:
        logger.error(f"AI处理异常: {e}", exc_info=True)
        raise  # 让上层统一处理事务回滚


def _retrieve_knowledge(content: str, history: list[dict]) -> list:
    """构建检索上下文并检索 RAG 知识

    - 简短输入（<5字）跳过 RAG 检索
    - 短追问（≤8字）自动拼上历史上下文增强检索
    """
    if len(content) < 5:
        return []
    enhanced_query = _build_enhanced_query(content, history)
    return KnowledgeService.search(enhanced_query)


def _generate_ai_reply(content: str, history: list[dict], knowledge_chunks: list, user_id: str) -> str:
    """调用 AI 生成回复（含转人工等待期策略）

    转人工等待期间：AI 继续安抚客户、回答知识范围内问题，但不做承诺。
    """
    handoff = HandoffService.get_handoff(user_id)
    is_waiting = handoff is not None
    messages = PromptBuilder.build_messages(
        user_input=content,
        knowledge_chunks=knowledge_chunks,
        conversation_history=history,
        is_handoff_waiting=is_waiting,
    )
    ai_service = _get_ai_service()
    return ai_service.chat(messages)


def _build_enhanced_query(current_input: str, history: list[dict]) -> str:
    """短追问时拼上历史上下文，提高RAG检索命中率

    规则：
    - > 8字：完整提问，直接用原始输入
    - ≤ 8字：从历史取最近1轮用户消息，拼成"{上下文} | {当前输入}"
    - 上下文截取前50字，防止超限
    """
    if len(current_input) > 8:
        return current_input

    user_count = 0
    for msg in reversed(history):
        if msg["role"] == "user":
            user_count += 1
            if user_count == 2:
                context = msg["content"][:50]
                logger.debug(f"增强检索: '{current_input}' → '{context} | {current_input}'")
                return f"{context} | {current_input}"

    return current_input


def _send_reply(reply: UnifiedReply):
    """发送回复到 IM 平台（commit 成功后调用，失败不影响数据库一致性）"""
    try:
        platform = get_platform(reply.platform)
        if platform:
            platform.send_message(reply)
    except Exception as e:
        logger.error(f"发送回复失败: {e}", exc_info=True)


def _save_message(conversation_id: int, role: str, content: str, msg_type: str, platform: str, image_path: str = None):
    """保存消息（使用 flush 保持事务边界）"""
    msg = Message(conversation_id=conversation_id, role=role, content=content, msg_type=msg_type, channel=platform, image_path=image_path)
    db.session.add(msg)
    db.session.flush()


def get_conversation_history(conversation_id: int, max_rounds: int = None) -> list[dict]:
    """获取对话历史"""
    if max_rounds is None:
        try:
            from app.models.models import AIConfig
            ai_config = AIConfig.query.first()
            max_rounds = ai_config.max_history_rounds if ai_config else current_app.config.get("MAX_HISTORY_ROUNDS", 10)
        except Exception:
            max_rounds = current_app.config.get("MAX_HISTORY_ROUNDS", 10)
    msgs = Message.query.filter(
        Message.conversation_id == conversation_id,
        Message.role.in_(["user", "assistant"]),
    ).order_by(Message.id.desc()).limit(max_rounds * 2).all()
    # 倒序取出的是"最近的 N*2 条"，反转成正序（先发的在前）
    msgs.reverse()
    history = []
    for m in msgs:
        role = "user" if m.role == "user" else "assistant"
        history.append({"role": role, "content": m.content})
    return history
