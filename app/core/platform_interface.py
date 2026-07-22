"""IM平台抽象接口

所有IM平台必须实现 PlatformInterface。
AI业务层只依赖此接口，不感知具体平台。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ==================== 统一消息模型 ====================

@dataclass
class UnifiedMessage:
    """统一消息模型 - AI业务层只认这个

    platform 负责将各平台原始消息解析为这个结构。
    """
    platform: str                 # 平台标识：wechat_work / feishu / dingtalk
    msg_id: str                   # 平台消息ID
    msg_type: str                 # text / image
    content: str                  # 文本内容（图片消息为OCR后文字）
    user_id: str                  # 发送者ID（平台用户ID）
    user_name: str = ""           # 发送者名称
    group_id: str | None = None   # 群ID（私聊为None）
    group_name: str | None = None # 群名称
    raw_data: dict = field(default_factory=dict)  # 原始数据


@dataclass
class UnifiedReply:
    """统一回复模型 - AI业务层产出这个"""
    platform: str                 # 目标平台
    user_id: str                  # 目标用户
    group_id: str | None = None   # 目标群（群聊时需要）
    content: str = ""             # 回复内容
    msg_type: str = "text"        # text / image


# ==================== 平台接口 ====================

class PlatformInterface(ABC):
    """所有IM平台必须实现的接口"""

    @abstractmethod
    def get_platform_type(self) -> str:
        """返回平台标识：wechat_work / feishu / dingtalk / telegram"""
        pass

    @abstractmethod
    def get_platform_name(self) -> str:
        """返回平台显示名称：企业微信 / 飞书 / 钉钉 / Telegram"""
        pass

    @abstractmethod
    def verify_request(self, request: Any) -> bool:
        """验证请求是否来自该平台（签名验证等）

        返回 True 表示请求合法，False 表示非法请求。
        """
        pass

    @abstractmethod
    def parse_message(self, request: Any) -> UnifiedMessage:
        """将平台原始请求解析为统一消息模型

        Args:
            request: Flask request 对象

        Returns:
            UnifiedMessage: 解析后的统一消息
        """
        pass

    @abstractmethod
    def send_message(self, reply: UnifiedReply) -> bool:
        """将统一回复发送到平台

        Args:
            reply: 统一回复模型

        Returns:
            bool: 是否发送成功
        """
        pass

    @abstractmethod
    def get_user_info(self, user_id: str) -> dict:
        """获取用户信息"""
        pass

    @abstractmethod
    def get_config_schema(self) -> dict:
        """返回平台配置的JSON Schema

        用于后台管理页面动态渲染配置表单。
        新增平台时只需在此定义配置项，后台无需修改。

        Returns:
            dict: {
                "fields": [
                    {"key": "corp_id", "label": "企业ID", "type": "text", "required": true},
                    ...
                ]
            }
        """
        pass

    @abstractmethod
    def test_connection(self, config: dict) -> dict:
        """测试平台连接是否正常

        Args:
            config: 平台配置信息

        Returns:
            dict: {"success": True/False, "message": "..."}
        """
        pass
