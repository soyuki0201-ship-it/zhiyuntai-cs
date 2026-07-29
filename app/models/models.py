"""数据模型

4张核心表 + 1张平台配置表 + 2张AI配置表：
- conversations: 对话表
- messages: 消息表
- handoffs: 接管表
- knowledge: 知识库原文表
- platform_configs: 平台配置表（多IM架构）
- ai_providers: AI模型供应商配置表
- ai_config: AI系统配置表（单例）
"""
from datetime import datetime
from app.models import db


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    channel = db.Column(db.String(32), nullable=False, comment="消息来源：wechat_work(企业微信) / feishu(飞书) / dingtalk(钉钉) 等平台标识")
    platform_config_id = db.Column(db.Integer, nullable=True, comment="平台配置ID，用于追溯具体配置实例")
    user_id = db.Column(db.String(128), nullable=False, comment="客户ID：平台用户唯一标识")
    group_id = db.Column(db.String(128), nullable=True, comment="群ID（仅群聊通道有值）")
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


class Knowledge(db.Model):
    __tablename__ = "knowledge"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(256), nullable=False, comment="知识标题")
    content = db.Column(db.Text, nullable=False, comment="知识内容")
    category = db.Column(db.String(64), nullable=True, comment="分类：产品功能介绍/产品常见问题/产品使用教程/付费相关/故障处理/需求提出/其他")
    source = db.Column(db.String(64), nullable=True, comment="来源：manual / chat / product")
    tags = db.Column(db.String(512), nullable=True, comment="标签（逗号分隔，方便分类筛选）")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.Index("idx_source", "source"),)


class AIProvider(db.Model):
    """AI模型供应商配置"""
    __tablename__ = "ai_providers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(128), nullable=False, comment="配置名称")
    provider = db.Column(db.String(64), nullable=False, comment="供应商标识：deepseek / openai / qwen / kimi / custom")
    model_name = db.Column(db.String(128), nullable=False, comment="模型名称：deepseek-chat / gpt-4o / qwen-plus 等")
    api_url = db.Column(db.String(512), nullable=False, comment="API 地址")
    api_key = db.Column(db.String(1024), nullable=False, comment="API Key（AES 加密存储）")
    is_primary = db.Column(db.Boolean, nullable=False, default=False, comment="是否主模型")
    enabled = db.Column(db.Boolean, nullable=False, default=True, comment="是否启用")
    sort_order = db.Column(db.Integer, nullable=False, default=0, comment="排序（主模型优先）")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index("idx_ai_enabled", "enabled"),
        db.Index("idx_ai_primary", "is_primary"),
    )


class Handoff(db.Model):
    __tablename__ = "handoffs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False)
    channel = db.Column(db.String(32), nullable=False, comment="来源通道")
    user_id = db.Column(db.String(128), nullable=False, comment="被接管的客户ID")
    user_name = db.Column(db.String(128), nullable=True, comment="用户显示名称（接管时记录）")
    reason = db.Column(db.Text, nullable=True, comment="转接原因（AI判断理由）")
    status = db.Column(db.String(16), nullable=False, default="active", comment="状态：active(接管中) / resolved(已释放)")
    handled_by = db.Column(db.String(64), nullable=True, comment="处理人企业微信ID")
    is_auto = db.Column(db.Boolean, nullable=False, default=False, comment="是否AI自动转人工（True=AI，False=运营主动接管）")
    taken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, comment="接管时间")
    last_active_at = db.Column(db.DateTime, nullable=True, comment="客户最后活跃时间（用于超时判断）")
    resolved_at = db.Column(db.DateTime, nullable=True, comment="释放时间")

    __table_args__ = (
        db.Index("idx_h_user_id", "user_id"),
        db.Index("idx_h_status", "status"),
        db.Index("idx_h_taken_at", "taken_at"),
    )


class AIConfig(db.Model):
    """AI系统配置（单例，包含系统设置持久化）"""
    __tablename__ = "ai_config"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ai_name = db.Column(db.String(128), nullable=False, default="智云台助手", comment="AI显示名称")
    system_prompt = db.Column(db.Text, nullable=False, comment="系统提示词")
    temperature = db.Column(db.Float, nullable=False, default=0.7, comment="回复温度 (0-1)")
    max_tokens = db.Column(db.Integer, nullable=False, default=2000, comment="单次最大Token数")
    max_history_rounds = db.Column(db.Integer, nullable=False, default=10, comment="对话保留轮数")
    handoff_markers = db.Column(db.Text, nullable=True, comment="转人工关键词（逗号分隔）")
    rag_top_k = db.Column(db.Integer, nullable=False, default=5, comment="检索TOP-K")
    rag_similarity_threshold = db.Column(db.Float, nullable=False, default=0.6, comment="相似度阈值")
    conversation_ttl_days = db.Column(db.Integer, nullable=False, default=30, comment="对话保留天数")
    handoff_timeout_minutes = db.Column(db.Integer, nullable=False, default=30, comment="接管超时释放分钟数")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
