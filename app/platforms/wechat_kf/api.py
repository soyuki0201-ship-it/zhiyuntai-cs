"""微信客服 API 封装

微信客服（WeChat KF）是企微官方客服方案。
客户从微信端（扫码/公众号/小程序）发起咨询，支持完整的消息回调推送和API回复能力。

API 文档参考：
- 获取 access_token：与企微自建应用相同
- 拉取消息：cgi-bin/kf/sync_msg
- 发送消息：cgi-bin/kf/send_msg
"""
import time
import json
import logging
import requests
from app.models import db
from sqlalchemy import text

logger = logging.getLogger(__name__)


class WeChatKFAPI:
    """微信客服 API 封装"""

    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict):
        self._config = config
        self.corp_id = config.get("corp_id", "")
        self.agent_secret = config.get("agent_secret", "")
        self.open_kfid = config.get("open_kfid", "")
        self._access_token = None
        self._token_expires_at = 0

    def get_access_token(self) -> str:
        """获取 access_token（与企微自建应用共享缓存机制）

        通过自建应用的 corp_id + agent_secret 获取。
        有本地缓存（有效期 7200 秒，提前 60 秒刷新）。
        """
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        url = f"{self.BASE_URL}/gettoken"
        params = {"corpid": self.corp_id, "corpsecret": self.agent_secret}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("errcode") != 0:
            raise Exception(f"获取 access_token 失败: {data.get('errmsg')}")

        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200)
        return self._access_token

    def sync_msg(self, cursor: str = "", token: str = "") -> dict:
        """拉取微信客服消息

        优先使用回调 Token（有效期 10 分钟），过期后回退到 access_token。
        cursor 为空时从最新消息开始拉取，非空时从断点续拉。

        Args:
            cursor: 游标（持久化在 kf_cursor 表中）
            token: 回调事件中的 Token（10 分钟有效期）

        Returns:
            dict: {"errcode": 0, "msg_list": [...], "next_cursor": "xxx", "has_more": 0}
        """
        access_token = self.get_access_token()
        url = f"{self.BASE_URL}/kf/sync_msg?access_token={access_token}"
        payload = {"cursor": cursor}
        if token:
            payload["token"] = token

        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") != 0:
            logger.error(f"sync_msg 失败: {data}")
            return data

        return data

    def send_msg(self, touser: str, msgtype: str, content: str) -> dict:
        """发送消息给客户

        微信客服限制：48 小时内最多回复 5 条消息。

        Args:
            touser: 客户 external_userid
            msgtype: 消息类型（text/image等）
            content: 文本内容

        Returns:
            dict: API 响应
        """
        access_token = self.get_access_token()
        url = f"{self.BASE_URL}/kf/send_msg?access_token={access_token}"

        payload = {
            "touser": touser,
            "open_kfid": self.open_kfid,
            "msgtype": msgtype,
            msgtype: {"content": content},
        }

        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()

        if data.get("errcode") != 0:
            logger.error(f"发送微信客服消息失败: {data}")
        else:
            logger.info(f"微信客服消息发送成功: touser={touser}")

        return data

    def get_cursor(self, kfid: str) -> str:
        """从数据库获取指定客服号的游标

        Args:
            kfid: 微信客服 open_kfid

        Returns:
            str: 游标值，不存在则返回空字符串
        """
        try:
            result = db.session.execute(
                text("SELECT cursor_val FROM kf_cursor WHERE kfid = :kfid"),
                {"kfid": kfid},
            ).scalar()
            return result or ""
        except Exception as e:
            logger.error(f"获取游标失败: {e}")
            return ""

    def save_cursor(self, kfid: str, cursor_val: str):
        """持久化游标到数据库

        Args:
            kfid: 微信客服 open_kfid
            cursor_val: 游标值
        """
        if not cursor_val:
            return
        try:
            db.session.execute(
                text("""
                    INSERT INTO kf_cursor (kfid, cursor_val)
                    VALUES (:kfid, :cursor_val)
                    ON DUPLICATE KEY UPDATE cursor_val = :cursor_val2
                """),
                {"kfid": kfid, "cursor_val": cursor_val, "cursor_val2": cursor_val},
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"持久化游标失败: {e}")

    def can_send(self, user_id: str) -> bool:
        """检查是否可以发送消息给该客户（48h/5条窗口）

        微信客服限制：
        - 48小时内客户未发消息则不可发送
        - 48小时内最多回复5条

        当前实现：简化为只检查时间窗口，消息条数由企微API在服务端控制。

        Args:
            user_id: 客户 ID

        Returns:
            bool: True 可以发送，False 超出窗口
        """
        try:
            from app.models.models import Message, Conversation
            from datetime import datetime, timedelta

            cutoff = datetime.utcnow() - timedelta(hours=48)
            recent = Message.query.join(
                Conversation, Message.conversation_id == Conversation.id
            ).filter(
                Message.role == "user",
                Message.channel == "wechat_kf",
                Conversation.user_id == user_id,
                Message.created_at > cutoff,
            ).order_by(Message.created_at.desc()).first()

            if recent is None:
                # 48小时内该客户没有发消息 → 不能主动发消息
                return False
            return True
        except Exception as e:
            logger.error(f"检查发送窗口失败: {e}")
            return False
