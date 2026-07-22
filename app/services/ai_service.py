"""AI 对话服务 - DeepSeek API 封装

负责与 DeepSeek API 通信，生成 AI 回复。
"""
import json
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)


class AIService:
    """DeepSeek AI 对话服务"""

    def __init__(self, app=None):
        self.api_key = None
        self.api_url = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.api_key = app.config["DEEPSEEK_API_KEY"]
        self.api_url = app.config["DEEPSEEK_API_URL"]

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        """调用 DeepSeek API 生成回复

        Args:
            messages: 对话消息列表
                [{"role": "system", "content": "..."},
                 {"role": "user", "content": "..."},
                 {"role": "assistant", "content": "..."}]
            temperature: 生成温度 (0-1)，越低越确定

        Returns:
            str: AI 回复内容
        """
        if not self.api_key:
            logger.warning("DeepSeek API Key 未配置，返回占位回复")
            return "【AI服务未配置，请在部署时设置 DeepSeek API Key】"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2000,
        }

        try:
            resp = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            reply = data["choices"][0]["message"]["content"]
            logger.info(f"DeepSeek 回复成功, tokens={data.get('usage', {})}")

            return reply.strip()

        except requests.exceptions.Timeout:
            logger.error("DeepSeek API 超时")
            return "抱歉，我暂时无法响应，请稍后再试。"

        except requests.exceptions.RequestException as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            return "抱歉，我遇到了一些技术问题，已转给人工客服处理。"

    def classify_intent(self, user_input: str) -> str:
        """识别用户意图分类

        Returns:
            str: 意图类别
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个客服意图分类器。请判断用户问题的类别，只返回一个词：\n"
                    "product_usage - 产品使用咨询\n"
                    "bug_report - 问题反馈/Bug\n"
                    "permission - 权限开通\n"
                    "business - 业务需求交流\n"
                    "other - 其他"
                ),
            },
            {"role": "user", "content": user_input},
        ]
        return self.chat(messages, temperature=0.1)
