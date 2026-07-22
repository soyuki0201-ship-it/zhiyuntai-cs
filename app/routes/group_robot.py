"""群机器人 Webhook 路由（过渡期兼容）

通过旧群机器人 URL 过来的请求，委托给新版平台模块处理。
新配置请走 /api/wechat_work/callback。
"""
import logging
import json
from threading import Thread
from flask import Blueprint, request, Response, current_app
from app.core.platform_interface import UnifiedMessage
from app.services.conversation_service import process_unified_message

logger = logging.getLogger(__name__)
group_robot_bp = Blueprint("group_robot", __name__)


@group_robot_bp.route("/group_robot", methods=["POST"])
def receive_group_message():
    """接收群聊消息（群机器人 Webhook 回调）"""
    token = request.args.get("token", "")
    expected_token = current_app.config.get("WX_GROUP_ROBOT_TOKEN", "")
    if expected_token and token != expected_token:
        logger.warning(f"群机器人 Token 验证失败")
        return "invalid token", 403

    try:
        data = request.get_json(force=True)
        logger.info(f"收到群消息: {json.dumps(data, ensure_ascii=False)[:200]}")

        thread = Thread(target=_handle_group_message, args=(data,))
        thread.daemon = True
        thread.start()

    except Exception as e:
        logger.error(f"群消息处理异常: {e}", exc_info=True)

    return Response("", mimetype="text/plain")


def _handle_group_message(data: dict):
    """异步处理群消息"""
    try:
        with current_app.app_context():
            items = data.get("item", [])
            for msg in items:
                unified = UnifiedMessage(
                    platform="wechat_work",
                    msg_id=msg.get("MsgId", ""),
                    msg_type="text",
                    content=msg.get("Content", ""),
                    user_id=msg.get("FromUserName", ""),
                    user_name=msg.get("FromUserName", ""),
                    group_id=msg.get("GroupId", ""),
                )
                process_unified_message(unified)
    except Exception as e:
        logger.error(f"异步处理群消息失败: {e}", exc_info=True)
