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
    """清理过期对话（从 AIConfig 表读取保留天数）

    Bug 13 修复：原代码不限 status，会把持续对话超 30 天的活跃客户也删掉。
    现在只清理 status=closed 的对话；active/transferred 状态保留。
    另外用批量 DELETE 替代逐条删除，减少大事务持锁。
    """
    from datetime import datetime, timedelta
    from app.models.models import db, Conversation, Message, Handoff, AIConfig

    cfg = AIConfig.query.first()
    ttl_days = cfg.conversation_ttl_days if cfg else 30
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)

    # Bug 13 修复：只清理已关闭且超保留期的对话，不删 active/transferred
    expired = Conversation.query.filter(
        Conversation.updated_at < cutoff,
        Conversation.status == "closed",
    ).all()

    if not expired:
        return

    expired_ids = [c.id for c in expired]

    # 批量删除关联数据
    Message.query.filter(Message.conversation_id.in_(expired_ids)).delete(synchronize_session=False)
    Handoff.query.filter(Handoff.conversation_id.in_(expired_ids)).delete(synchronize_session=False)
    Conversation.query.filter(Conversation.id.in_(expired_ids)).delete(synchronize_session=False)

    db.session.commit()
    logger.info(f"数据清理：已清理 {len(expired_ids)} 条已关闭的过期对话（保留{ttl_days}天）")
