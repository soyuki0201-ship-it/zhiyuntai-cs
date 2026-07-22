"""统一回调入口路由

所有IM平台的回调请求统一经过此路由：
/api/{platform}/callback

平台标识从URL路径中提取，自动路由到对应平台的 handler。
"""
import logging
from flask import Blueprint, request, Response, current_app
from threading import Thread
from app.core.platform_manager import get_platform
from app.core.platform_interface import UnifiedMessage
from app.services.conversation_service import process_unified_message

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/<platform>/callback", methods=["GET", "POST"])
def platform_callback(platform: str):
    """统一平台回调入口

    所有平台的回调都走这里：
    - GET  /api/wechat_work/callback  (企微回调URL验证)
    - POST /api/wechat_work/callback  (企微消息推送)
    - POST /api/feishu/callback       (飞书消息推送，未来)
    - POST /api/dingtalk/callback     (钉钉消息推送，未来)
    """
    platform_instance = get_platform(platform)
    if not platform_instance:
        logger.warning(f"未知平台回调: {platform}")
        return "platform not found", 404

    # GET 请求：回调URL验证
    if request.method == "GET":
        try:
            # 平台模块自己处理验证逻辑
            from flask import current_app
            return platform_instance.handle_verification(request)
        except Exception as e:
            logger.error(f"平台回调验证失败: {platform} - {e}")
            return "verification failed", 403

    # POST 请求：消息推送
    # 先验证请求合法性
    if not platform_instance.verify_request(request):
        logger.warning(f"平台请求验证失败: {platform}")
        return "invalid request", 403

    # 异步处理消息（先返回200，再慢慢处理）
    thread = Thread(
        target=_handle_platform_message,
        args=(platform_instance, request, platform_instance._config_id),
    )
    thread.daemon = True
    thread.start()

    return Response("", mimetype="text/plain")


def _handle_platform_message(platform, request, platform_config_id=None):
    """异步处理平台消息"""
    try:
        with current_app.app_context():
            # 1. 解析为统一消息
            message = platform.parse_message(request)
            message.platform_config_id = platform_config_id

            # 2. 交给业务层处理（业务层不感知平台）
            process_unified_message(message)

    except Exception as e:
        logger.error(f"平台消息处理失败: {platform.get_platform_type()} - {e}", exc_info=True)
