"""企业微信客户联系（私聊）回调路由（过渡期兼容）

通过旧回调 URL 过来的请求，委托给新版平台模块处理。
新配置请走 /api/wechat_work/callback。
"""
import logging
import xml.etree.ElementTree as ET
from threading import Thread
from flask import Blueprint, request, Response, current_app
from app.platforms.wechat_work import WeChatWorkPlatform
from app.core.platform_interface import UnifiedMessage
from app.services.conversation_service import process_unified_message

logger = logging.getLogger(__name__)
callback_bp = Blueprint("callback", __name__)


def _build_platform():
    """从 app.config 构建企业微信平台实例（过渡期用）"""
    cfg = current_app.config
    return WeChatWorkPlatform({
        "corp_id": cfg.get("WX_CORP_ID", ""),
        "agent_secret": cfg.get("WX_AGENT_SECRET", ""),
        "agent_id": cfg.get("WX_AGENT_ID", ""),
        "token": cfg.get("WX_TOKEN", ""),
        "encoding_aes_key": cfg.get("WX_ENCODING_AES_KEY", ""),
    })


@callback_bp.route("/external_contact", methods=["GET"])
def verify_url():
    """企业微信回调 URL 验证（GET 请求）"""
    try:
        platform = _build_platform()
        echo_decrypted = platform.handle_verification(request)
        return Response(echo_decrypted, mimetype="text/plain")
    except Exception as e:
        logger.error(f"回调 URL 验证失败: {e}")
        return "verification failed", 403


@callback_bp.route("/external_contact", methods=["POST"])
def receive_message():
    """接收客户消息（POST 请求）"""
    try:
        platform = _build_platform()
        thread = Thread(target=_handle_message, args=(platform, request))
        thread.daemon = True
        thread.start()
    except Exception as e:
        logger.error(f"消息处理异常: {e}", exc_info=True)
    return Response("", mimetype="text/plain")


def _handle_message(platform, request):
    """异步处理消息"""
    try:
        with current_app.app_context():
            message = platform.parse_message(request)
            process_unified_message(message)
    except Exception as e:
        logger.error(f"异步处理消息失败: {e}", exc_info=True)
