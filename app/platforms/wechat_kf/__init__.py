"""微信客服平台模块

实现 PlatformInterface，新增 wechat_kf 平台类型。
微信客服回调走独立 Blueprint（/api/kf/callback），不走统一入口。
但 PlatformInterface 全部接口仍需实现，保持架构完整。

消息处理流程与其他平台不同：
1. 回调收到事件通知（加密XML）→ 验签解密 → 入MySQL队列 → 立即返回 success
2. worker 轮询队列 → 用回调 Token 调 sync_msg 拉取实际消息
3. sync_msg 返回的消息由本模块转换为 UnifiedMessage → 进入现有 AI 业务层

密码学：复用 crypto.py 的 WecomMsgCrypto，用微信客服独立的 Token/EncodingAESKey 初始化实例。
"""
import json
import logging
from flask import request as flask_request
from app.core.platform_interface import PlatformInterface, UnifiedMessage, UnifiedReply
from app.platforms.wechat_work.crypto import WecomMsgCrypto
from app.platforms.wechat_kf.api import WeChatKFAPI

logger = logging.getLogger(__name__)


class WeChatKFPlatform(PlatformInterface):
    """微信客服平台实现"""

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._crypto = None
        self._api = None

    def get_platform_type(self) -> str:
        return "wechat_kf"

    def get_platform_name(self) -> str:
        return "微信客服"

    def _get_crypto(self):
        if self._crypto is None:
            cfg = self._config
            self._crypto = WecomMsgCrypto(
                token=cfg.get("token", ""),
                encoding_aes_key=cfg.get("encoding_aes_key", ""),
                receive_id=cfg.get("corp_id", ""),
            )
        return self._crypto

    def _get_api(self):
        if self._api is None:
            self._api = WeChatKFAPI(self._config)
        return self._api

    def handle_verification(self, request) -> str:
        """处理回调 URL 验证（GET 请求）

        微信客服回调 URL 验证与企微自建应用完全一致：
        - msg_signature = SHA1(sorted(Token + Timestamp + Nonce + EchoStr))
        - AES-256-CBC 解密 EchoStr → 取消息体
        - 校验尾部 receive_id == corpid
        """
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echo_str = request.args.get("echostr", "")
        crypto = self._get_crypto()
        return crypto.verify_url(msg_signature, timestamp, nonce, echo_str)

    def verify_request(self, request) -> bool:
        """验证 POST 回调请求签名"""
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
        """解析回调请求为统一消息

        微信客服回调 POST 请求是加密 XML 格式的事件通知。
        实际消息内容需要后续调 sync_msg 拉取，此处仅解析事件信息。

        注意：worker 从 sync_msg 拉取消息后，应使用 parse_sync_msg() 转换。
        """
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        encrypted_xml = request.data.decode("utf-8")
        crypto = self._get_crypto()
        xml_text = crypto.decrypt_message(msg_signature, timestamp, nonce, encrypted_xml)

        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        event_type = root.findtext("Event", "")
        token = root.findtext("Token", "")
        open_kfid = root.findtext("OpenKfId", "")

        return UnifiedMessage(
            platform="wechat_kf",
            msg_id=root.findtext("MsgId", "") or root.findtext("CreateTime", ""),
            msg_type="event",
            content=json.dumps({"event": event_type, "token": token, "open_kfid": open_kfid}),
            user_id=root.findtext("ExternalUserID", "") or "",
            user_name="",
            raw_data={
                "event": event_type,
                "token": token,
                "open_kfid": open_kfid,
                "xml_text": xml_text,
            },
        )

    @staticmethod
    def parse_sync_msg(msg_data: dict) -> UnifiedMessage | None:
        """将 sync_msg API 返回的单条消息转换为 UnifiedMessage

        sync_msg 返回的消息格式：
        {
            "msgid": "msg_xxx",
            "senderid": "wx_xxx",        # 客户 external_userid
            "recvierid": "kf_xxx",       # 客服号 open_kfid
            "msgtype": "text",
            "content": {"text": {"content": "您好"}},
            "send_time": 1234567890
        }

        Args:
            msg_data: sync_msg 返回的消息列表中的一条

        Returns:
            UnifiedMessage | None: 解析失败返回 None
        """
        try:
            msgid = msg_data.get("msgid", "")
            senderid = msg_data.get("senderid", "")
            msgtype = msg_data.get("msgtype", "text")
            send_time = msg_data.get("send_time", 0)

            # 提取文本内容
            content = ""
            if msgtype == "text":
                content = msg_data.get("content", {}).get("text", {}).get("content", "")
            elif msgtype == "image":
                content = "[图片]"
            elif msgtype == "voice":
                content = "[语音]"
            elif msgtype == "video":
                content = "[视频]"
            else:
                content = json.dumps(msg_data.get("content", {}), ensure_ascii=False)

            return UnifiedMessage(
                platform="wechat_kf",
                msg_id=msgid,
                msg_type=msgtype,
                content=content,
                user_id=senderid,
                user_name="",
                raw_data=msg_data,
            )
        except Exception as e:
            logger.error(f"解析 sync_msg 消息失败: {e}")
            return None

    def send_message(self, reply: UnifiedReply) -> bool:
        """发送回复消息

        微信客服限制：
        - 48 小时内客户未发消息则不可发送
        - 48 小时内最多回复 5 条（企微服务端控制）
        """
        try:
            api = self._get_api()
            if not api.can_send(reply.user_id):
                logger.warning(f"微信客服 48h 窗口关闭，不发送消息: user={reply.user_id}")
                return False
            result = api.send_msg(reply.user_id, "text", reply.content)
            return result.get("errcode") == 0
        except Exception as e:
            logger.error(f"微信客服发送消息失败: {e}")
            return False

    def get_user_info(self, user_id: str) -> dict:
        """获取用户信息

        微信客服获取客户信息需走不同 API，当前暂不实现。
        """
        return {}

    def get_config_schema(self) -> dict:
        """微信客服配置 Schema

        注意：
        - Token/EncodingAESKey 是微信客服独立配置的，与企微自建应用不同
        - corp_id/agent_id/agent_secret 复用企微自建应用的（用于获取 access_token）
        - open_kfid 在创建微信客服号时获得
        """
        return {
            "platform": "wechat_kf",
            "name": "微信客服",
            "fields": [
                {"key": "corp_id", "label": "企业ID（CorpID）", "type": "text", "required": True},
                {"key": "agent_id", "label": "应用AgentID", "type": "text", "required": True},
                {"key": "agent_secret", "label": "应用Secret", "type": "password", "required": True},
                {"key": "open_kfid", "label": "微信客服ID（open_kfid）", "type": "text", "required": True},
                {"key": "token", "label": "回调Token", "type": "text", "required": True},
                {"key": "encoding_aes_key", "label": "回调EncodingAESKey", "type": "text", "required": True},
                {"key": "callback_url", "label": "回调地址", "type": "text", "readonly": True},
            ],
        }

    def test_connection(self, config: dict) -> dict:
        """测试连接：验证 access_token 和 open_kfid 是否有效"""
        try:
            api = WeChatKFAPI(config)
            token = api.get_access_token()
            if token:
                return {"success": True, "message": "连接成功，access_token 已获取"}
            return {"success": False, "message": "获取 access_token 失败"}
        except Exception as e:
            return {"success": False, "message": str(e)}
