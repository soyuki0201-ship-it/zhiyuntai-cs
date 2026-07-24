"""对话服务（平台无关版）

接收 UnifiedMessage，处理 AI 对话，产出 UnifiedReply。
平台接入层 -> UnifiedMessage -> 此模块 -> UnifiedReply -> 平台发送层
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
            return
        _save_message(conversation.id, "user", message.content, message.msg_type, message.platform, message.image_path)
        _handle_ai_response(conversation, message)
    except Exception as e:
        logger.error(f"处理消息异常: {e}", exc_info=True)


def _get_or_create_conversation(user_id: str, user_name: str, group_id: str | None, group_name: str | None, platform: str, platform_config_id: int | None = None) -> Conversation:
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
        db.session.commit()
        return conv
    conv = Conversation(channel=platform, user_id=user_id, user_name=user_name,
                        group_id=group_id, group_name=group_name, status="active",
                        platform_config_id=platform_config_id)
    db.session.add(conv)
    db.session.commit()
    return conv


def _handle_ai_response(conversation: Conversation, message: UnifiedMessage):
    try:
        content = message.content.strip()
        # 先读历史（既用于增强检索，也用于最终Prompt）
        history = get_conversation_history(conversation.id)

        # 简短输入（<5字）跳过 RAG 检索
        if len(content) >= 5:
            enhanced_query = _build_enhanced_query(content, history)
            knowledge_chunks = KnowledgeService.search(enhanced_query)
        else:
            knowledge_chunks = []

        handoff = HandoffService.get_handoff(message.user_id)
        is_waiting = handoff is not None
        messages = PromptBuilder.build_messages(user_input=content, knowledge_chunks=knowledge_chunks, conversation_history=history, is_handoff_waiting=is_waiting)
        ai_service = _get_ai_service()
        reply = ai_service.chat(messages)
        should_handoff = PromptBuilder.check_should_handoff(reply)
        if should_handoff:
            _save_message(conversation.id, "assistant", reply, "text", message.platform)
            HandoffService.take_over(message.user_id)
            conversation.status = "transferred"
            db.session.commit()
        else:
            _save_message(conversation.id, "assistant", reply, "text", message.platform)
            _send_reply(message, reply)
    except Exception as e:
        logger.error(f"AI处理异常: {e}", exc_info=True)


def _build_enhanced_query(current_input: str, history: list[dict]) -> str:
    """短追问时拼上历史上下文，提高RAG检索命中率

    规则：
    - > 8字：完整提问，直接用原始输入
    - ≤ 8字：从历史取最近1轮用户消息，拼成"{上下文} | {当前输入}"
    - 上下文截取前50字，防止超限

    Args:
        current_input: 用户当前输入（已strip）
        history: 对话历史（role + content）

    Returns:
        str: 增强后的检索query
    """
    # 完整提问（>8字）不需要增强
    if len(current_input) > 8:
        return current_input

    # 从历史找当前输入的上一轮用户消息
    # 注意：当前输入已在 process_unified_message 中存入数据库，
    # 所以 history 最后一条 user 消息就是当前输入本身
    user_count = 0
    for msg in reversed(history):
        if msg["role"] == "user":
            user_count += 1
            if user_count == 2:  # 第2条 = 上一轮的用户提问
                context = msg["content"][:50]
                logger.debug(f"增强检索: '{current_input}' → '{context} | {current_input}'")
                return f"{context} | {current_input}"

    # 没有历史消息（首轮提问），直接返回
    return current_input


def _send_reply(original_message: UnifiedMessage, content: str):
    reply = UnifiedReply(platform=original_message.platform, user_id=original_message.user_id, group_id=original_message.group_id, content=content)
    platform = get_platform(original_message.platform)
    if platform:
        platform.send_message(reply)


def _save_message(conversation_id: int, role: str, content: str, msg_type: str, platform: str, image_path: str = None):
    msg = Message(conversation_id=conversation_id, role=role, content=content, msg_type=msg_type, channel=platform, image_path=image_path)
    db.session.add(msg)
    db.session.commit()


def get_conversation_history(conversation_id: int, max_rounds: int = None) -> list[dict]:
    if max_rounds is None:
        # 优先从 AIConfig 表读取，兜底使用 config.py 默认值
        try:
            from app.models.models import AIConfig
            ai_config = AIConfig.query.first()
            max_rounds = ai_config.max_history_rounds if ai_config else current_app.config.get("MAX_HISTORY_ROUNDS", 10)
        except Exception:
            max_rounds = current_app.config.get("MAX_HISTORY_ROUNDS", 10)
    msgs = Message.query.filter(
        Message.conversation_id == conversation_id,
        Message.role.in_(["user", "assistant"]),
    ).order_by(Message.created_at.asc()).limit(max_rounds * 2).all()
    history = []
    for m in msgs:
        role = "user" if m.role == "user" else "assistant"
        history.append({"role": role, "content": m.content})
    return history
