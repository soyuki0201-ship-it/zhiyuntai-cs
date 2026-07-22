"""平台配置模型

管理所有IM平台的接入配置。
支持动态新增平台类型，无需修改表结构。

config_json 字段在存储时进行 AES 加密，
读取时自动解密，业务层无感知。
"""
import os
import base64
import json
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.models import db


def _get_encryption_key() -> bytes:
    """从 SECRET_KEY 派生加密密钥

    SECRET_KEY 来自环境变量，部署时配置。
    必须确保 __init__.py 中的启动检查先于首次调用。
    """
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY 未配置，无法进行加密操作")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"zhiyuntai-platform-config",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    return key


def _encrypt_json(data: dict) -> str:
    """加密配置 JSON"""
    fernet = Fernet(_get_encryption_key())
    plain_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    encrypted = fernet.encrypt(plain_text.encode("utf-8"))
    return encrypted.decode("utf-8")


def _decrypt_json(encrypted_str: str) -> dict:
    """解密配置 JSON"""
    try:
        fernet = Fernet(_get_encryption_key())
        plain_text = fernet.decrypt(encrypted_str.encode("utf-8"))
        return json.loads(plain_text.decode("utf-8"))
    except Exception:
        # 如果是未加密的老数据（明文 JSON），直接解析返回
        try:
            return json.loads(encrypted_str)
        except Exception:
            return {}


class PlatformConfig(db.Model):
    __tablename__ = "platform_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    platform = db.Column(
        db.String(32), nullable=False,
        comment="平台标识：wechat_work / feishu / dingtalk",
    )
    name = db.Column(
        db.String(128), nullable=False,
        comment="配置名称（如'企业微信-生产环境'）",
    )
    enabled = db.Column(
        db.Boolean, nullable=False, default=True,
        comment="是否启用",
    )
    config_json = db.Column(
        db.Text, nullable=False,
        comment="平台配置JSON（加密存储）",
    )
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow,
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.Index("idx_platform", "platform"),
    )

    def set_config(self, config: dict):
        """设置配置（自动加密存储）"""
        self.config_json = _encrypt_json(config)

    def get_config(self) -> dict:
        """获取配置（自动解密读取）"""
        return _decrypt_json(self.config_json)
