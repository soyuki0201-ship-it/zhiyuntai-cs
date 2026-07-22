"""平台配置模型

管理所有IM平台的接入配置。
支持动态新增平台类型，无需修改表结构。
"""
from datetime import datetime
from app.models import db


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
        db.JSON, nullable=False,
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
