"""微信客服回调入口

微信客服回调处理流程与其他平台不同，走独立 Blueprint。

处理流程：
1. GET 请求：回调 URL 验证（同企微自建应用的 SHA1 签名验证）
2. POST 请求（加密XML）：
   ① 验签 + AES解密 → 提取事件（Token/OpenKfId/Event）
   ② 消息入 MySQL 队列（5秒内返回 "success"）
   ③ worker 轮询队列 → sync_msg 拉取 → AI处理

回调地址：/api/kf/callback（实际域名部署后确定）
"""
import logging
import xml.etree.ElementTree as ET
from flask import Blueprint, request, Response
from app.core.platform_manager import get_platform
from app.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

kf_bp = Blueprint("kf", __name__, url_prefix="/api/kf")


@kf_bp.route("/callback", methods=["GET", "POST"])
@rate_limit(max_requests=60, window_seconds=60)
def kf_callback():
    """微信客服回调统一入口

    GET: 回调 URL 验证（企微后台配置回调地址时触发）
    POST: 事件推送（用户发消息、客服状态变更等）
    """
    platform = get_platform("wechat_kf")

    if request.method == "GET":
        # 回调 URL 验证：与企微自建应用完全相同的流程
        if not platform:
            return "platform not found", 404
        try:
            return platform.handle_verification(request)
        except Exception as e:
            logger.error(f"微信客服回调验证失败: {e}")
            return "verification failed", 403

    # POST 请求：事件推送
    try:
        if not platform:
            logger.warning("微信客服平台未注册，无法处理回调")
            return "success", 200

        # 1. 验签 + 解密
        crypto = platform._get_crypto()
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        encrypted_xml = request.data.decode("utf-8")

        xml_text = crypto.decrypt_message(msg_signature, timestamp, nonce, encrypted_xml)

        # 2. 提取事件数据
        root = ET.fromstring(xml_text)
        event_data = {
            "event": root.findtext("Event", ""),
            "token": root.findtext("Token", ""),
            "open_kfid": root.findtext("OpenKfId", ""),
            "create_time": root.findtext("CreateTime", ""),
        }

        # 3. 入 MySQL 队列（异步处理）
        from app.services.kf_message_queue import enqueue_event
        enqueue_event(event_data)

    except Exception as e:
        # 验签解密失败也要返回 success（企微会重试）
        logger.error(f"微信客服回调处理异常: {e}", exc_info=True)

    # 必须 5 秒内返回 "success"
    return Response("success", mimetype="text/plain")
