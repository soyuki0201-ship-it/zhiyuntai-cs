"""微信客服消息队列服务

使用 MySQL 表替代 Redis，实现异步消息处理。
适用于 <50条/天的量级，零额外运维成本。

处理流程：
1. 回调入口验签解密后写入 kf_queue 表（status=pending）
2. worker 轮询拉取 pending 事件
3. 用回调 Token 调 sync_msg 拉取实际消息
4. 转换为 UnifiedMessage → conversation_service.process_unified_message()
5. 标记事件为 done
"""
import json
import logging
from datetime import datetime
from app.models import db
from sqlalchemy import text

logger = logging.getLogger(__name__)


def enqueue_event(event_data: dict) -> int:
    """将回调事件写入消息队列

    Args:
        event_data: 回调事件数据（包含 Token、OpenKfId、时间戳等）

    Returns:
        int: 队列记录 ID，-1 表示失败
    """
    try:
        result = db.session.execute(
            text("INSERT INTO kf_queue (event_data) VALUES (:data)"),
            {"data": json.dumps(event_data, ensure_ascii=False)},
        )
        db.session.commit()
        row_id = result.lastrowid
        logger.debug(f"回调事件已入队: id={row_id}")
        return row_id
    except Exception as e:
        db.session.rollback()
        logger.error(f"事件入队失败: {e}")
        return -1


def process_queue(app):
    """轮询处理消息队列（在后台线程中运行）

    从 kf_queue 表拉取 pending 事件，逐个处理。
    处理完成后更新 status=done。

    Args:
        app: Flask 应用实例（用于获取 app_context）
    """
    with app.app_context():
        try:
            # 拉取 pending 事件（每次最多 10 条）
            events = db.session.execute(
                text("SELECT id, event_data FROM kf_queue WHERE status = 'pending' ORDER BY id ASC LIMIT 10")
            ).fetchall()

            if not events:
                return

            logger.info(f"消息队列: 发现 {len(events)} 个待处理事件")

            for row in events:
                try:
                    _process_event(app, row.id, row.event_data)
                except Exception as e:
                    logger.error(f"处理事件失败: id={row.id}, error={e}")

        except Exception as e:
            logger.error(f"队列轮询异常: {e}")


def _process_event(app, event_id: int, event_data_str: str):
    """处理单个回调事件

    1. 解析事件数据（提取 Token、OpenKfId）
    2. 查找对应的微信客服平台实例
    3. 调用 sync_msg 拉取消息
    4. 将每条消息转换为 UnifiedMessage → 进入 AI 处理
    5. 持久化游标
    6. 标记事件为 done
    """
    from app.core.platform_manager import get_platform

    event_data = json.loads(event_data_str)
    token = event_data.get("token", "")
    open_kfid = event_data.get("open_kfid", "")
    event_type = event_data.get("event", "")

    # 只处理 kf_msg_or_event 事件（消息/事件通知）
    if event_type not in ("kf_msg_or_event", ""):
        _mark_done(event_id)
        return

    # 查找 wechat_kf 平台实例
    platform = get_platform("wechat_kf")
    if not platform:
        logger.warning(f"微信客服平台未注册，跳过事件: id={event_id}")
        _mark_done(event_id)
        return

    api = platform._get_api()

    # 获取游标 + 回调 Token（10 分钟有效期，过期回退到 access_token）
    cursor = api.get_cursor(open_kfid)
    access_token = api.get_access_token()

    try:
        # 先用回调 Token 拉取
        result = api.sync_msg(cursor=cursor, token=token)
    except Exception:
        # Token 过期，回退到 access_token
        logger.info(f"回调 Token 过期，回退到 access_token: open_kfid={open_kfid}")
        result = api.sync_msg(cursor=cursor, token="")

    if result.get("errcode") != 0:
        logger.error(f"sync_msg 拉取失败: {result}")
        _mark_done(event_id)
        return

    # 处理消息列表
    msg_list = result.get("msg_list", [])
    next_cursor = result.get("next_cursor", "")

    for msg_data in msg_list:
        try:
            # 只处理客户发送的消息（非系统事件）
            if msg_data.get("msgtype") in ("event", ""):
                continue

            # 转换为 UnifiedMessage
            message = platform.parse_sync_msg(msg_data)
            if message is None:
                continue

            # 幂等去重
            from app.utils.idempotent import is_duplicate
            if is_duplicate(message.msg_id):
                logger.debug(f"消息重复跳过: msgid={message.msg_id}")
                continue

            # 标记平台配置 ID
            message.platform_config_id = getattr(platform, '_config_id', None)

            # 进入 AI 业务层
            from app.services.conversation_service import process_unified_message
            process_unified_message(message)

        except Exception as e:
            logger.error(f"处理消息异常: msgid={msg_data.get('msgid', '')}, error={e}")

    # 持久化游标（只有拉取成功才更新）
    if next_cursor:
        api.save_cursor(open_kfid, next_cursor)

    # 标记事件为 done
    _mark_done(event_id)
    logger.info(f"事件处理完成: id={event_id}, msgs={len(msg_list)}")


def _mark_done(event_id: int):
    """标记队列事件为已完成"""
    try:
        db.session.execute(
            text("UPDATE kf_queue SET status = 'done' WHERE id = :id AND status = 'pending'"),
            {"id": event_id},
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"标记事件完成失败: id={event_id}, error={e}")


def get_pending_count() -> int:
    """获取待处理的队列事件数量"""
    try:
        count = db.session.execute(
            text("SELECT COUNT(*) FROM kf_queue WHERE status = 'pending'")
        ).scalar()
        return count or 0
    except Exception:
        return 0
