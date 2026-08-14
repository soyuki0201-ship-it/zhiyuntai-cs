"""人工接管服务

按架构设计文档第5章「人工接管机制」实现。

并发安全策略：
- take_over 使用 SELECT ... FOR UPDATE 锁住用户行，防止多 worker 重复创建
- 所有数据库操作在一个事务内完成，由调用方统一 commit/rollback
"""
import logging
from datetime import datetime, timedelta
from app.models.models import db, Conversation, Handoff, Message

logger = logging.getLogger(__name__)


class HandoffService:

    @staticmethod
    def take_over(user_id: str, handled_by: str = None, is_auto: bool = False) -> bool:
        """接管用户（并发安全，使用 SELECT FOR UPDATE）

        注意：不在此方法内 commit()。由 process_unified_message 统一 commit。
        """
        conv = Conversation.query.filter_by(user_id=user_id, status="active").first()
        if not conv:
            conv = Conversation.query.filter_by(user_id=user_id, status="transferred").first()
        if not conv:
            logger.warning(f"接管失败：客户 {user_id} 无活跃对话")
            return False

        # 使用 SELECT ... FOR UPDATE 锁定该用户的 handoff 行，防止并发重复创建
        existing = Handoff.query.with_for_update().filter_by(user_id=user_id, status="active").first()
        if existing:
            existing.handled_by = handled_by
            existing.is_auto = is_auto
            existing.taken_at = datetime.utcnow()
            logger.info(f"更新已有接管记录: user_id={user_id}")
            return True

        reason = "AI自动转人工" if is_auto else "运营主动接管"
        handoff = Handoff(
            conversation_id=conv.id, channel=conv.channel, user_id=user_id,
            user_name=conv.user_name, reason=reason, status="active",
            is_auto=is_auto, handled_by=handled_by,
            taken_at=datetime.utcnow(), last_active_at=datetime.utcnow(),
        )
        db.session.add(handoff)
        conv.status = "transferred"
        return True

    @staticmethod
    def release(user_id: str) -> bool:
        """释放用户接管（注意：外层调用方统一 commit）

        Bug 11 修复：释放时同时把 Conversation.status 从 transferred 恢复为 active，
        否则下次用户发消息会创建新会话（重复会话 Bug）。
        """
        handoff = Handoff.query.filter_by(user_id=user_id, status="active").first()
        if not handoff:
            return False
        handoff.status = "resolved"
        handoff.resolved_at = datetime.utcnow()
        # 恢复会话状态为 active，让 AI 能正常回复
        conv = Conversation.query.filter_by(id=handoff.conversation_id).first()
        if conv and conv.status == "transferred":
            conv.status = "active"
        return True

    @staticmethod
    def is_handed_over(user_id: str) -> bool:
        """检查用户是否已被接管（读操作，不需要锁）"""
        return Handoff.query.filter_by(user_id=user_id, status="active").first() is not None

    @staticmethod
    def get_handoff(user_id: str) -> Handoff | None:
        return Handoff.query.filter_by(user_id=user_id, status="active").first()

    @staticmethod
    def check_and_release_timeout() -> int:
        """检查并释放超时接管（定时任务调用，独立事务）"""
        from app.models.models import AIConfig
        cfg = AIConfig.query.first()
        timeout_minutes = cfg.handoff_timeout_minutes if cfg else 30
        timeout = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        expired = Handoff.query.filter(Handoff.status == "active", Handoff.last_active_at < timeout).all()
        for handoff in expired:
            handoff.status = "resolved"
            handoff.resolved_at = datetime.utcnow()
            # 同步恢复会话状态（与 release 一致）
            conv = Conversation.query.filter_by(id=handoff.conversation_id).first()
            if conv and conv.status == "transferred":
                conv.status = "active"
        if expired:
            db.session.commit()
        return len(expired)

    @staticmethod
    def update_last_active(user_id: str):
        """更新用户最后活跃时间（读操作，由调用方统一 commit）"""
        handoff = Handoff.query.filter_by(user_id=user_id, status="active").first()
        if handoff:
            handoff.last_active_at = datetime.utcnow()

    @staticmethod
    def get_all_active(page: int = 1, per_page: int = 20) -> tuple:
        """获取运营已接管的处理中列表（is_auto=False）"""
        pagination = Handoff.query.filter_by(status="active", is_auto=False).order_by(Handoff.taken_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total

    @staticmethod
    def get_pending_count() -> int:
        """AI自动转人工但尚未被运营接管的数量（is_auto=True且status=active）"""
        return Handoff.query.filter_by(status="active", is_auto=True).count()

    @staticmethod
    def get_processing_count() -> int:
        """运营已接管正在处理中的数量（is_auto=False且status=active）"""
        return Handoff.query.filter_by(status="active", is_auto=False).count()
