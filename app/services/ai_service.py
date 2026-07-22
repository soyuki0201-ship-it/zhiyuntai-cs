"""AI 对话服务 - DeepSeek API 封装

负责与 DeepSeek API 通信，生成 AI 回复。
"""
import json
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)


class AIService:
    """AI 对话服务（从数据库读取模型配置）"""

    def __init__(self, app=None):
        self.api_key = None
        self.api_url = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.api_key = app.config["DEEPSEEK_API_KEY"]
        self.api_url = app.config["DEEPSEEK_API_URL"]

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        """调用 AI API 生成回复（从数据库读取主模型配置）

        Args:
            messages: 对话消息列表
            temperature: 生成温度 (0-1)，越低越确定

        Returns:
            str: AI 回复内容
        """
        # 尝试从数据库读取已启用的模型配置
        provider = None
        try:
            from app.models.models import AIProvider
            # 先找主模型
            provider = AIProvider.query.filter_by(enabled=True, is_primary=True).first()
            if not provider:
                # 找第一个启用的
                provider = AIProvider.query.filter_by(enabled=True).order_by(AIProvider.sort_order).first()
        except Exception:
            pass

        if provider:
            # 使用数据库中的模型配置
            return self._call_provider(provider.api_url, provider.api_key, provider.model_name, messages, temperature)

        # 回退：使用 config.py 中的 DeepSeek 配置
        if not self.api_key:
            logger.warning("AI 模型未配置，返回占位回复")
            return "【AI服务未配置，请在管理后台 AI 配置中添加模型】"

        return self._call_provider(self.api_url, self.api_key, "deepseek-chat", messages, temperature)

    def _call_provider(self, api_url: str, api_key: str, model_name: str,
                       messages: list[dict], temperature: float) -> str:
        """调用指定 AI 供应商的 API"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2000,
        }

        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            reply = data["choices"][0]["message"]["content"]
            logger.info(f"AI 回复成功, model={model_name}, tokens={data.get('usage', {})}")

            return reply.strip()

        except requests.exceptions.Timeout:
            logger.error(f"AI API 超时: {api_url}")
            return "抱歉，我暂时无法响应，请稍后再试。"

        except requests.exceptions.RequestException as e:
            logger.error(f"AI API 调用失败: {api_url} - {e}")
            return "抱歉，我遇到了一些技术问题，已转给人工客服处理。"


def test_provider_connection(api_url: str, api_key: str, model_name: str) -> dict:
    """测试AI模型连接是否正常"""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
        }
        resp = requests.post(api_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return {"success": True, "message": f"{model_name} 连接成功"}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "连接超时"}
    except Exception as e:
        return {"success": False, "message": str(e)}
