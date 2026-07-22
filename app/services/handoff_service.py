"""人工接管服务

按架构设计文档第5章「人工接管机制」实现。
"""
import logging
from datetime import datetime, timedelta
from app.models.models import db, Conversation, Handoff, Message

logger = logging.getLogger(__name__)


class HandoffService:
    TIMEOUT_MINUTES = 30

    @staticmethod
    def take_over(user_id: str, handled_by: str = None) -> bool:
        conv = Conversation.query.filter_by(user_id=user_id, status="active").first()
        if not conv:
            conv = Conversation.query.filter_by(user_id=user_id, status="transferred").first()
        if not conv:
            logger.warning(f"接管失败：客户 {user_id} 无活跃对话")
            return False

        handoff = Handoff.query.filter_by(user_id=user_id, status="active").first()
        if handoff:
            handoff.handled_by = handled_by
            handoff.taken_at = datetime.utcnow()
            db.session.commit()
            return True

        handoff = Handoff(
            conversation_id=conv.id, channel=conv.channel, user_id=user_id,
            user_name=conv.user_name, reason="运营主动接管", status="active",
            handled_by=handled_by, taken_at=datetime.utcnow(), last_active_at=datetime.utcnow(),
        )
        db.session.add(handoff)
        conv.status = "transferred"
        db.session.commit()
        return True

    @staticmethod
    def release(user_id: str) -> bool:
        handoff = Handoff.query.filter_by(user_id=user_id, status="active").first()
        if not handoff:
            return False
        handoff.status = "resolved"
        handoff.resolved_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def is_handed_over(user_id: str) -> bool:
        return Handoff.query.filter_by(user_id=user_id, status="active").first() is not None

    @staticmethod
    def get_handoff(user_id: str) -> Handoff | None:
        return Handoff.query.filter_by(user_id=user_id, status="active").first()

    @staticmethod
    def check_and_release_timeout() -> int:
        timeout = datetime.utcnow() - timedelta(minutes=HandoffService.TIMEOUT_MINUTES)
        expired = Handoff.query.filter(Handoff.status == "active", Handoff.last_active_at < timeout).all()
        for handoff in expired:
            handoff.status = "resolved"
            handoff.resolved_at = datetime.utcnow()
        if expired:
            db.session.commit()
        return len(expired)

    @staticmethod
    def update_last_active(user_id: str):
        handoff = Handoff.query.filter_by(user_id=user_id, status="active").first()
        if handoff:
            handoff.last_active_at = datetime.utcnow()
            db.session.commit()

    @staticmethod
    def get_all_active(page: int = 1, per_page: int = 20) -> tuple:
        pagination = Handoff.query.filter_by(status="active").order_by(Handoff.taken_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total

    @staticmethod
    def get_pending_count() -> int:
        return Handoff.query.filter_by(status="active").count()
