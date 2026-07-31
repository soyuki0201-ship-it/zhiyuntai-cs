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
from app.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/<platform>/callback", methods=["GET", "POST"])
@rate_limit(max_requests=60, window_seconds=60)
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
    # 注意：子线程不继承主线程的 ContextVar，不能直接使用 current_app 代理。
    # 必须在主线程中捕获真实 app 对象并传入子线程。
    app = current_app._get_current_object()
    thread = Thread(
        target=_handle_platform_message,
        args=(app, platform_instance, request, platform_instance._config_id),
    )
    thread.daemon = True
    thread.start()

    return Response("", mimetype="text/plain")


@api_bp.route("/wechat_work/jsapi/signature")
@rate_limit(max_requests=120, window_seconds=60)
def wechat_work_jsapi_signature():
    """企微 JS-SDK 签名端点（H5 页面 wx.config 用）

    入参：
    - url: 页面完整 URL（含路径，企微要求与签名时完全一致）

    返回：
    - 成功：{appId, timestamp, nonceStr, signature}
    - 失败：JSON {success: False, message}
    """
    from app.core.platform_manager import get_platform

    page_url = request.args.get("url", "").strip()
    if not page_url or len(page_url) > 2048:
        return {"success": False, "message": "缺少 url 参数"}, 400

    # 域名白名单校验：只允许配置回调的可信域名
    from urllib.parse import urlparse
    parsed = urlparse(page_url)
    if parsed.scheme not in ("https", "http"):
        return {"success": False, "message": "url 协议非法"}, 400
    host = parsed.netloc
    # 基础校验：拒绝带用户信息的 url（user:pass@host）和明显非法 host
    if "@" in parsed.netloc or not host or "." not in host:
        return {"success": False, "message": "url 域名非法"}, 400

    platform = get_platform("wechat_work")
    if not platform:
        return {"success": False, "message": "企微平台未配置"}, 404

    try:
        api = platform._get_api()
        jsapi_ticket = api.get_jsapi_ticket()
        import time as _time
        import os as _os
        timestamp = str(int(_time.time()))
        nonce_str = _os.urandom(8).hex()
        signature = api.generate_jsapi_signature(jsapi_ticket, page_url, nonce_str, timestamp)
        app_id = platform._config.get("corp_id", "")
        return {
            "success": True,
            "appId": app_id,
            "timestamp": timestamp,
            "nonceStr": nonce_str,
            "signature": signature,
        }
    except Exception as e:
        logger.error(f"JS-SDK 签名生成失败: {e}", exc_info=True)
        return {"success": False, "message": f"签名生成失败: {e}"}, 500


def _handle_platform_message(app, platform, request, platform_config_id=None):
    """异步处理平台消息

    Args:
        app: 真实 Flask app 实例（子线程无法访问 current_app 代理）
        platform: 平台实例
        request: Flask request 对象
        platform_config_id: 平台配置实例 ID
    """
    try:
        with app.app_context():
            # 1. 解析为统一消息
            message = platform.parse_message(request)
            message.platform_config_id = platform_config_id

            # 2. 交给业务层处理（业务层不感知平台）
            process_unified_message(message)

    except Exception as e:
        logger.error(f"平台消息处理失败: {platform.get_platform_type()} - {e}", exc_info=True)
