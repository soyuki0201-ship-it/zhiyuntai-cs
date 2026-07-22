import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration from environment variables."""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # MySQL
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "zhiyuntai_cs")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
        f"?charset=utf8mb4"
    )

    # WeChat Work - 已迁移至数据库 platform_configs 表管理
    WX_CORP_ID = os.getenv("WX_CORP_ID", "")
    WX_AGENT_ID = os.getenv("WX_AGENT_ID", "")
    WX_AGENT_SECRET = os.getenv("WX_AGENT_SECRET", "")
    WX_TOKEN = os.getenv("WX_TOKEN", "")
    WX_ENCODING_AES_KEY = os.getenv("WX_ENCODING_AES_KEY", "")
    WX_GROUP_ROBOT_TOKEN = os.getenv("WX_GROUP_ROBOT_TOKEN", "")
    WX_GROUP_ROBOT_WEBHOOK_URL = os.getenv("WX_GROUP_ROBOT_WEBHOOK_URL", "")

    # DeepSeek
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

    # Embedding model
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh")

    # ChromaDB
    CHROMA_PERSIST_DIR = os.getenv(
        "CHROMA_PERSIST_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chroma_db"),
    )

    # Knowledge base
    KNOWLEDGE_TABLE = "knowledge"

    # Conversation
    MAX_HISTORY_ROUNDS = 10
    CONVERSATION_TTL_DAYS = 30
    HANDOFF_TIMEOUT_MINUTES = 30

    # RAG
    RAG_TOP_K = 5
    RAG_SIMILARITY_THRESHOLD = 0.6

    # Image
    IMAGE_CACHE_DIR = os.getenv(
        "IMAGE_CACHE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "image_cache"),
    )

    # Admin auth
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
