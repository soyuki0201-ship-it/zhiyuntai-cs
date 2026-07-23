"""定时任务管理

按架构设计文档要求实现：
- D4 超时释放定时器：每5分钟检查接管超时（30分钟），自动释放
- D5 数据清理定时器：每天凌晨3点清理30天前的对话记录
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def init_scheduler(app):
    """初始化定时任务

    架构文档 7.2：使用 APScheduler 轻量定时任务，与应用同进程
    开发计划 D4/D5：超时释放检测 + 数据清理
    """
    scheduler = BackgroundScheduler()

    # D4：每5分钟检查一次接管超时
    @scheduler.scheduled_job("interval", minutes=5, id="check_handoff_timeout")
    def check_timeout():
        with app.app_context():
            from app.services.handoff_service import HandoffService
            try:
                count = HandoffService.check_and_release_timeout()
                if count > 0:
                    logger.info(f"超时释放检查：{count} 个接管已超时自动释放")
            except Exception as e:
                logger.error(f"超时释放检查异常: {e}")

    # D5：每天凌晨3点清理30天前的对话记录
    @scheduler.scheduled_job("cron", hour=3, minute=0, id="cleanup_old_data")
    def cleanup_data():
        with app.app_context():
            try:
                _cleanup_expired_conversations()
            except Exception as e:
                logger.error(f"数据清理异常: {e}")

    scheduler.start()
    logger.info("定时任务已启动")


def _cleanup_expired_conversations():
    """清理30天前的过期对话"""
    from datetime import datetime, timedelta
    from app.models.models import db, Conversation, Message, Handoff

    cutoff = datetime.utcnow() - timedelta(days=30)

    # 查找30天前无更新的对话（不限状态）
    expired = Conversation.query.filter(
        Conversation.updated_at < cutoff,
    ).all()

    for conv in expired:
        # 删除关联消息
        Message.query.filter_by(conversation_id=conv.id).delete()
        # 删除关联接管记录
        Handoff.query.filter_by(conversation_id=conv.id).delete()
        # 删除对话本身
        db.session.delete(conv)

    if expired:
        db.session.commit()
        logger.info(f"数据清理：已清理 {len(expired)} 条过期对话")
