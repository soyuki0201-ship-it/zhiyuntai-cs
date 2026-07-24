from flask import Flask
from app.config import Config
from app.models import db
from app.utils.scheduler import init_scheduler
from app.core.platform_manager import register_platform


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class)

    # 检查 SECRET_KEY（生产环境必须配置）
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY 未配置！请在 .env 文件中设置 SECRET_KEY 为随机字符串。"
            "示例：SECRET_KEY=your-random-secret-key-here"
        )

    # Session 配置
    app.config["SESSION_PERMANENT"] = True

    # Init database
    db.init_app(app)

    # Register routes
    from app.routes.api import api_bp
    from app.routes.admin import admin_bp
    from app.routes.platform_configs import admin_config_bp
    from app.routes.ai_config import ai_config_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_config_bp)
    app.register_blueprint(ai_config_bp)

    # 旧路由：已下线，通过新统一入口 /api/wechat_work/callback 处理
    # 保留 callback.py / group_robot.py 文件用于参考，后续版本删除
    # 不再自动注册旧路由，避免新旧配置路径混淆

    # Init scheduler
    if not app.config.get("TESTING"):
        init_scheduler(app)

    # Register platforms
    with app.app_context():
        _register_platforms(app)

    # Embedding model (deploy-time, can fail gracefully)
    with app.app_context():
        try:
            from app.utils.vector_store import init_vector_store
            init_vector_store(
                persist_dir=app.config["CHROMA_PERSIST_DIR"],
                model_name=app.config["EMBEDDING_MODEL_NAME"],
            )
            app.logger.info("Embedding 模型加载成功")
        except Exception as e:
            app.logger.error(f"Embedding 模型加载失败，RAG 知识库检索不可用: {e}")
            app.logger.error("请确认：1) 网络能访问 HuggingFace  2) 磁盘空间充足  3) sentence-transformers 已安装")

    return app


def _register_platforms(app):
    """从数据库读取已启用的平台配置并注册"""
    try:
        from app.models.platform_config import PlatformConfig
        from app.core.platform_manager import get_platform_class

        configs = PlatformConfig.query.filter_by(enabled=True).all()
        for pc in configs:
            try:
                platform_cls = get_platform_class(pc.platform)
                if platform_cls:
                    instance = platform_cls(pc.get_config())
                    instance._config_id = pc.id
                    register_platform(instance)
                    app.logger.info(f"平台已加载: {pc.platform} ({pc.name})")
            except Exception as e:
                app.logger.error(f"平台 {pc.platform}({pc.name}) 加载失败: {e}")
    except Exception as e:
        app.logger.warning(f"平台加载失败（首次运行时正常）: {e}")
