"""数据模型

4张核心表 + 1张平台配置表：
- conversations: 对话表
- messages: 消息表
- handoffs: 接管表
- knowledge: 知识库原文表
- platform_configs: 平台配置表（多IM架构）
"""
from datetime import datetime
from app.models import db


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    channel = db.Column(db.String(32), nullable=False, comment="消息来源：wechat_work(企业微信) / feishu(飞书) / dingtalk(钉钉) 等平台标识")
    user_id = db.Column(db.String(64), nullable=False, comment="客户ID：平台用户唯一标识")
    group_id = db.Column(db.String(64), nullable=True, comment="群ID（仅群聊通道有值）")
    user_name = db.Column(db.String(128), nullable=True, comment="用户显示名称")
    group_name = db.Column(db.String(128), nullable=True, comment="群显示名称")
    status = db.Column(db.String(16), nullable=False, default="active", comment="状态：active / transferred / closed")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship("Message", backref="conversation", lazy="dynamic")
    handoffs = db.relationship("Handoff", backref="conversation", lazy="dynamic")

    __table_args__ = (
        db.Index("idx_user_id", "user_id"),
        db.Index("idx_group_id", "group_id"),
        db.Index("idx_status", "status"),
    )


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    role = db.Column(db.String(16), nullable=False, comment="消息角色：user / assistant / system")
    content = db.Column(db.Text, nullable=False, comment="消息内容（图片消息为OCR提取的文字）")
    msg_type = db.Column(db.String(16), nullable=False, default="text", comment="消息类型：text / image")
    image_path = db.Column(db.String(256), nullable=True, comment="图片消息：本地缓存的图片路径")
    channel = db.Column(db.String(32), nullable=False, comment="消息来源平台标识")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_conversation", "conversation_id"),
        db.Index("idx_created_at", "created_at"),
    )


class Handoff(db.Model):
    __tablename__ = "handoffs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    channel = db.Column(db.String(32), nullable=False, comment="来源通道")
    user_id = db.Column(db.String(64), nullable=False, comment="被接管的客户ID")
    user_name = db.Column(db.String(128), nullable=True, comment="用户显示名称（接管时记录）")
    reason = db.Column(db.Text, nullable=True, comment="转接原因（AI判断理由）")
    status = db.Column(db.String(16), nullable=False, default="active", comment="状态：active(接管中) / resolved(已释放)")
    handled_by = db.Column(db.String(64), nullable=True, comment="处理人企业微信ID")
    taken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, comment="接管时间")
    last_active_at = db.Column(db.DateTime, nullable=True, comment="客户最后活跃时间（用于超时判断）")
    resolved_at = db.Column(db.DateTime, nullable=True, comment="释放时间")

    __table_args__ = (
        db.Index("idx_h_user_id", "user_id"),
        db.Index("idx_h_status", "status"),
    )


class Knowledge(db.Model):
    __tablename__ = "knowledge"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(256), nullable=False, comment="知识标题")
    content = db.Column(db.Text, nullable=False, comment="知识内容")
    source = db.Column(db.String(64), nullable=True, comment="来源：manual / chat / product")
    tags = db.Column(db.String(512), nullable=True, comment="标签（逗号分隔，方便分类筛选）")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.Index("idx_source", "source"),)
