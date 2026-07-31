"""微信客服消息幂等去重工具

基于 MySQL kf_msg_log 表实现，msgid 唯一索引 + INSERT IGNORE。
不引入 Redis，与项目现有技术栈一致。
"""

import logging
from datetime import datetime
from app.models import db
from sqlalchemy import text

logger = logging.getLogger(__name__)


def is_duplicate(msgid: str) -> bool:
    """检查消息是否已处理过（幂等去重）

    基于 kf_msg_log 表的 msgid 唯一索引实现。
    第一次调用 INSERT 成功 → 返回 False（未重复）
    第二次调用 INSERT IGNORE 失败 → 返回 True（已重复）

    Args:
        msgid: 微信客服消息 ID

    Returns:
        bool: True 表示已处理过（重复），False 表示首次收到
    """
    if not msgid:
        return False
    try:
        result = db.session.execute(
            text("INSERT IGNORE INTO kf_msg_log (msgid) VALUES (:msgid)"),
            {"msgid": msgid},
        )
        db.session.commit()
        # 影响行数为 0 说明 msgid 已存在（重复）
        return result.rowcount == 0
    except Exception as e:
        db.session.rollback()
        logger.error(f"幂等去重检查失败: {e}")
        # 容错：去重失败时不阻断消息处理，允许重复（避免丢失消息）
        return False
