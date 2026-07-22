from flask import Flask
from flask_httpauth import HTTPBasicAuth
from app.config import Config
from app.models import db
from app.utils.scheduler import init_scheduler
from app.core.platform_manager import register_platform

auth = HTTPBasicAuth()


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class)

    # Init database
    db.init_app(app)

    # Register routes
    from app.routes.api import api_bp
    from app.routes.admin import admin_bp
    from app.routes.platform_configs import admin_config_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_config_bp)

    # 旧路由（过渡期保留，后续删除）
    try:
        from app.routes.callback import callback_bp
        app.register_blueprint(callback_bp)
    except Exception:
        pass
    try:
        from app.routes.group_robot import group_robot_bp
        app.register_blueprint(group_robot_bp)
    except Exception:
        pass

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
        except Exception as e:
            app.logger.warning(f"Embedding 模型加载失败（部署后再配置）: {e}")

    return app


def _register_platforms(app):
    """从数据库读取已启用的平台配置并注册"""
    try:
        from app.models.platform_config import PlatformConfig
        from app.core.platform_manager import get_platform_class

        configs = PlatformConfig.query.filter_by(enabled=True).all()
        for pc in configs:
            platform_cls = get_platform_class(pc.platform)
            if platform_cls:
                instance = platform_cls(pc.config_json)
                register_platform(instance)
                app.logger.info(f"平台已加载: {pc.platform} ({pc.name})")
    except Exception as e:
        app.logger.warning(f"平台加载失败（首次运行时正常）: {e}")
