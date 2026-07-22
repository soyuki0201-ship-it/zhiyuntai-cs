"""AI 对话服务 - 支持多模型配置

负责与 AI API 通信，生成 AI 回复。
优先使用 AIProvider 表中配置的主模型，无配置时回退 DeepSeek。
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
        self.model_name = "deepseek-chat"
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.api_key = app.config.get("DEEPSEEK_API_KEY", "")
        self.api_url = app.config.get("DEEPSEEK_API_URL", "")
        self.model_name = "deepseek-chat"

    def chat(self, messages: list[dict], temperature: float = None) -> str:
        """调用 AI API 生成回复（从数据库读取主模型配置和参数）

        Args:
            messages: 对话消息列表
            temperature: 生成温度 (0-1)，默认从 AIConfig 读取

        Returns:
            str: AI 回复内容
        """
        api_url, api_key, model_name, cfg_temperature, max_tokens = self._get_provider_config()
        temperature = temperature if temperature is not None else cfg_temperature

        if not api_key:
            logger.warning("AI 模型未配置，返回占位回复")
            return "【AI服务未配置，请在管理后台 AI 配置中添加模型】"

        return self._call_api(api_url, api_key, model_name, messages, temperature, max_tokens)

    def _get_provider_config(self):
        """从数据库读取已启用的模型配置和 AI 参数"""
        try:
            from app.models.models import AIProvider, AIConfig
            from app.models.platform_config import _decrypt_json

            provider = (AIProvider.query.filter_by(enabled=True, is_primary=True).first()
                        or AIProvider.query.filter_by(enabled=True).order_by(AIProvider.sort_order).first())
            if provider:
                decrypted = _decrypt_json(provider.api_key)
                api_key = decrypted.get("key", provider.api_key)
                # 从 AIConfig 读取 temperature 和 max_tokens
                ai_config = AIConfig.query.first()
                cfg_temp = ai_config.temperature if ai_config else 0.7
                cfg_max_tokens = ai_config.max_tokens if ai_config else 2000
                return provider.api_url, api_key, provider.model_name, cfg_temp, cfg_max_tokens
        except Exception:
            pass

        # 回退：使用 config.py 中的 DeepSeek 配置
        return self.api_url, self.api_key, self.model_name, 0.7, 2000

    def _call_api(self, api_url: str, api_key: str, model_name: str,
                  messages: list[dict], temperature: float, max_tokens: int = 2000) -> str:
        """调用指定 AI 供应商的 API"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
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
