"""企业微信平台模块

实现 PlatformInterface，将企业微信所有逻辑集中在此目录。
AI业务层和后台通过统一接口访问，不直接依赖企微。
"""
import logging
import xml.etree.ElementTree as ET
from flask import current_app
from app.core.platform_interface import PlatformInterface, UnifiedMessage, UnifiedReply
from app.platforms.wechat_work.crypto import WeChatWorkCrypto
from app.platforms.wechat_work.api import WeChatWorkAPI

logger = logging.getLogger(__name__)


class WeChatWorkPlatform(PlatformInterface):

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._crypto = None
        self._api = None

    def get_platform_type(self) -> str:
        return "wechat_work"

    def get_platform_name(self) -> str:
        return "企业微信"

    def _get_crypto(self):
        if self._crypto is None:
            cfg = self._config
            self._crypto = WeChatWorkCrypto(
                token=cfg.get("token", ""),
                encoding_aes_key=cfg.get("encoding_aes_key", ""),
                receive_id=cfg.get("corp_id", ""),
            )
        return self._crypto

    def _get_api(self):
        if self._api is None:
            self._api = WeChatWorkAPI(self._config)
        return self._api

    def handle_verification(self, request) -> str:
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echo_str = request.args.get("echostr", "")
        crypto = self._get_crypto()
        return crypto.verify_url(msg_signature, timestamp, nonce, echo_str)

    def verify_request(self, request) -> bool:
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        encrypted_xml = request.data.decode("utf-8")
        try:
            crypto = self._get_crypto()
            crypto.decrypt_message(msg_signature, timestamp, nonce, encrypted_xml)
            return True
        except Exception:
            return False

    def parse_message(self, request) -> UnifiedMessage:
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        encrypted_xml = request.data.decode("utf-8")
        crypto = self._get_crypto()
        xml_text = crypto.decrypt_message(msg_signature, timestamp, nonce, encrypted_xml)
        root = ET.fromstring(xml_text)
        msg_data = {}
        for child in root:
            msg_data[child.tag] = child.text or ""
        msg_type = msg_data.get("MsgType", "text")
        content = msg_data.get("Content", "")
        user_id = msg_data.get("FromUserName", "")
        group_id = msg_data.get("GroupId", "")
        msg_id = msg_data.get("MsgId", "")
        user_name = msg_data.get("FromUserName", "")
        image_path = None
        if msg_type == "image":
            content, image_path = self._process_image(msg_data)
        return UnifiedMessage(
            platform="wechat_work", msg_id=msg_id,
            msg_type="text" if msg_type == "image" else msg_type,
            content=content, user_id=user_id, user_name=user_name,
            group_id=group_id if group_id else None, image_path=image_path, raw_data=msg_data,
        )

    def send_message(self, reply: UnifiedReply) -> bool:
        try:
            api = self._get_api()
            if reply.group_id:
                webhook_url = self._config.get("group_robot_webhook", "")
                if webhook_url:
                    return api.send_group_robot_message(webhook_url, reply.content)
                return False
            else:
                result = api.send_text_message(reply.user_id, reply.content)
                return result.get("errcode") == 0
        except Exception as e:
            logger.error(f"企业微信发送消息失败: {e}")
            return False

    def get_user_info(self, user_id: str) -> dict:
        try:
            api = self._get_api()
            return api.get_external_contact(user_id) or {}
        except Exception as e:
            logger.error(f"获取企业微信用户信息失败: {e}")
            return {}

    def _process_image(self, msg_data: dict) -> tuple[str, str | None]:
        import os
        import requests as http_req
        from app.utils.ocr import extract_text_from_image
        media_id = msg_data.get("MediaId", "")
        if not media_id:
            return "[图片]（未能识别）", None
        try:
            api = self._get_api()
            token = api.get_access_token()
            resp = http_req.get("https://qyapi.weixin.qq.com/cgi-bin/media/get",
                                params={"access_token": token, "media_id": media_id}, timeout=30)
            cache_dir = current_app.config.get("IMAGE_CACHE_DIR", "/tmp/image_cache")
            os.makedirs(cache_dir, exist_ok=True)
            local_path = os.path.join(cache_dir, f"{media_id}.jpg")
            with open(local_path, "wb") as f:
                f.write(resp.content)
            text = extract_text_from_image(local_path)
            content = f"[图片内容] {text}" if text else "[图片]（未能识别图中文字）"
            return content, local_path
        except Exception as e:
            logger.error(f"图片处理失败: {e}")
            return "[图片]（处理失败）", None

    def get_config_schema(self) -> dict:
        return {
            "platform": "wechat_work", "name": "企业微信",
            "fields": [
                {"key": "corp_id", "label": "企业ID（CorpID）", "type": "text", "required": True},
                {"key": "agent_id", "label": "应用AgentID", "type": "text", "required": True},
                {"key": "agent_secret", "label": "应用Secret", "type": "password", "required": True},
                {"key": "token", "label": "回调Token", "type": "text", "required": True},
                {"key": "encoding_aes_key", "label": "回调EncodingAESKey", "type": "text", "required": True},
                {"key": "callback_url", "label": "回调地址", "type": "text", "readonly": True},
                {"key": "group_robot_webhook", "label": "群机器人Webhook", "type": "text", "required": False},
            ],
        }

    def test_connection(self, config: dict) -> dict:
        try:
            api = WeChatWorkAPI(config)
            api.get_access_token()
            return {"success": True, "message": "连接成功，Token已获取"}
        except Exception as e:
            return {"success": False, "message": str(e)}
