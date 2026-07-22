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
        )
        if HandoffService.is_handed_over(message.user_id):
            HandoffService.update_last_active(message.user_id)
            _save_message(conversation.id, "user", message.content, message.msg_type, message.platform)
            return
        _save_message(conversation.id, "user", message.content, message.msg_type, message.platform)
        _handle_ai_response(conversation, message)
    except Exception as e:
        logger.error(f"处理消息异常: {e}", exc_info=True)


def _get_or_create_conversation(user_id: str, user_name: str, group_id: str | None, group_name: str | None, platform: str) -> Conversation:
    if group_id:
        conv = Conversation.query.filter_by(group_id=group_id, user_id=user_id, status="active").first()
    else:
        conv = Conversation.query.filter_by(user_id=user_id, status="active").first()
    if conv:
        if user_name:
            conv.user_name = user_name
        if group_name:
            conv.group_name = group_name
        conv.updated_at = datetime.utcnow()
        db.session.commit()
        return conv
    conv = Conversation(channel=platform, user_id=user_id, user_name=user_name, group_id=group_id, group_name=group_name, status="active")
    db.session.add(conv)
    db.session.commit()
    return conv


def _handle_ai_response(conversation: Conversation, message: UnifiedMessage):
    try:
        knowledge_chunks = KnowledgeService.search(message.content)
        history = get_conversation_history(conversation.id)
        handoff = HandoffService.get_handoff(message.user_id)
        is_waiting = handoff is not None
        messages = PromptBuilder.build_messages(user_input=message.content, knowledge_chunks=knowledge_chunks, conversation_history=history, is_handoff_waiting=is_waiting)
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


def _send_reply(original_message: UnifiedMessage, content: str):
    reply = UnifiedReply(platform=original_message.platform, user_id=original_message.user_id, group_id=original_message.group_id, content=content)
    platform = get_platform(original_message.platform)
    if platform:
        platform.send_message(reply)


def _save_message(conversation_id: int, role: str, content: str, msg_type: str, platform: str):
    msg = Message(conversation_id=conversation_id, role=role, content=content, msg_type=msg_type, channel=platform)
    db.session.add(msg)
    db.session.commit()


def get_conversation_history(conversation_id: int, max_rounds: int = 10) -> list[dict]:
    msgs = Message.query.filter(
        Message.conversation_id == conversation_id,
        Message.role.in_(["user", "assistant"]),
    ).order_by(Message.created_at.asc()).limit(max_rounds * 2).all()
    history = []
    for m in msgs:
        role = "user" if m.role == "user" else "assistant"
        history.append({"role": role, "content": m.content})
    return history
