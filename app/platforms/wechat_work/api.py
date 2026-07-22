"""企业微信API封装"""
import time
import requests
import logging

logger = logging.getLogger(__name__)


class WeChatWorkAPI:
    """企业微信API封装"""

    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, config: dict):
        self._config = config
        self.corp_id = config.get("corp_id", "")
        self.agent_secret = config.get("agent_secret", "")
        self._access_token = None
        self._token_expires_at = 0

    def get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        url = f"{self.BASE_URL}/gettoken"
        params = {"corpid": self.corp_id, "corpsecret": self.agent_secret}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("errcode") != 0:
            raise Exception(f"获取access_token失败: {data.get('errmsg')}")

        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200)
        return self._access_token

    def send_text_message(self, user_id: str, content: str) -> dict:
        token = self.get_access_token()
        url = f"{self.BASE_URL}/message/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self._config.get("agent_id", ""),
            "text": {"content": content},
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"发送消息失败: {data}")
        return data

    def send_group_robot_message(self, webhook_url: str, content: str) -> bool:
        """通过群机器人 Webhook 发送群聊消息"""
        try:
            payload = {"msgtype": "text", "text": {"content": content}}
            resp = requests.post(webhook_url, json=payload, timeout=10)
            return resp.ok
        except Exception as e:
            logger.error(f"企微群机器人发送失败: {e}")
            return False

    def get_external_contact(self, user_id: str) -> dict | None:
        token = self.get_access_token()
        url = f"{self.BASE_URL}/externalcontact/get"
        params = {"access_token": token, "external_userid": user_id}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("errcode") != 0:
            return None
        return data.get("external_contact")
