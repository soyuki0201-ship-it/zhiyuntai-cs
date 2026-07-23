"""管理后台路由 - 平台配置

新增【平台配置】菜单，支持动态管理所有IM平台的接入信息。
"""
import json
import logging
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from app.models.platform_config import PlatformConfig
from app.models import db
from app.core.platform_manager import get_platform_class, register_platform
from app.utils.csrf import generate_csrf_token, csrf_protected

logger = logging.getLogger(__name__)
admin_config_bp = Blueprint("admin_config", __name__, url_prefix="/admin")


def admin_required(f):
    """Session 登录校验装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_config_bp.context_processor
def inject_csrf_token():
    """注入 CSRF Token 生成函数到所有模板"""
    return dict(csrf_token=generate_csrf_token)


@admin_config_bp.route("/platforms")
@admin_required
def platform_list():
    """平台配置列表"""
    configs = PlatformConfig.query.order_by(PlatformConfig.platform).all()
    return render_template("admin/platform_list.html", configs=configs)


@admin_config_bp.route("/platforms/add", methods=["GET", "POST"])
@admin_required
def platform_add():
    """新增平台配置"""
    if request.method == "POST":
        # CSRF 验证
        token = request.headers.get("X-CSRFToken", "") or request.form.get("csrf_token", "")
        from app.utils.csrf import verify_csrf_token
        if not verify_csrf_token(token):
            return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403

        platform = request.form.get("platform", "")
        name = request.form.get("name", "")
        enabled = request.form.get("enabled", "1") == "1"

        # 收集动态配置项
        config_json = {}
        platform_cls = get_platform_class(platform)
        if platform_cls:
            schema = platform_cls({}).get_config_schema()
            for field in schema.get("fields", []):
                key = field["key"]
                value = request.form.get(f"cfg_{key}", "")
                if value:
                    config_json[key] = value

        pc = PlatformConfig(
            platform=platform,
            name=name,
            enabled=enabled,
            config_json="",
        )
        pc.set_config(config_json)
        db.session.add(pc)
        db.session.commit()

        # 动态注册平台实例
        _register_platform_from_config(pc)

        return redirect(url_for("admin_config.platform_list"))

    # GET: 展示可用的平台类型，并预加载第一个平台的 schema
    available = [
        {"type": "wechat_work", "name": "企业微信"},
    ]
    schema = {"fields": []}
    if available:
        cls = get_platform_class(available[0]["type"])
        if cls:
            schema = cls({}).get_config_schema()
    return render_template("admin/platform_form.html", config=None, available=available, schema=schema)


@admin_config_bp.route("/platforms/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def platform_edit(pid):
    """编辑平台配置"""
    pc = PlatformConfig.query.get_or_404(pid)

    if request.method == "POST":
        # CSRF 验证
        token = request.headers.get("X-CSRFToken", "") or request.form.get("csrf_token", "")
        from app.utils.csrf import verify_csrf_token
        if not verify_csrf_token(token):
            return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403

        pc.name = request.form.get("name", pc.name)
        pc.enabled = request.form.get("enabled", "1") == "1"

        # 更新配置项：先加载旧配置，合并表单提交的值
        old_config = pc.get_config()
        platform_cls = get_platform_class(pc.platform)
        if platform_cls:
            schema = platform_cls({}).get_config_schema()
            for field in schema.get("fields", []):
                key = field["key"]
                value = request.form.get(f"cfg_{key}")
                if value is not None:
                    old_config[key] = value

        # 更新配置项（合并后自动加密存储）
        pc.set_config(old_config)
        db.session.commit()

        # 重新注册
        _register_platform_from_config(pc)

        return redirect(url_for("admin_config.platform_list"))

    platform_cls = get_platform_class(pc.platform)
    schema = platform_cls({}).get_config_schema() if platform_cls else {"fields": []}

    return render_template("admin/platform_form.html", config=pc, available=[], schema=schema)


@admin_config_bp.route("/platforms/<int:pid>/delete", methods=["POST"])
@admin_required
def platform_delete(pid):
    """删除平台配置"""
    # CSRF 验证
    token = request.headers.get("X-CSRFToken", "") or request.form.get("csrf_token", "")
    from app.utils.csrf import verify_csrf_token
    if not verify_csrf_token(token):
        return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403
    pc = PlatformConfig.query.get_or_404(pid)
    db.session.delete(pc)
    db.session.commit()
    return redirect(url_for("admin_config.platform_list"))


@admin_config_bp.route("/platforms/<int:pid>/test", methods=["POST"])
@admin_required
def platform_test(pid):
    """测试平台连接"""
    # CSRF 验证
    token = request.form.get("csrf_token", "")
    from app.utils.csrf import verify_csrf_token
    if not verify_csrf_token(token):
        return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403

    pc = PlatformConfig.query.get_or_404(pid)
    platform_cls = get_platform_class(pc.platform)
    if not platform_cls:
        return jsonify({"success": False, "message": "未知平台类型"})

    instance = platform_cls(pc.get_config())
    result = instance.test_connection(pc.get_config())
    return jsonify(result)


def _register_platform_from_config(pc: PlatformConfig):
    """根据数据库配置注册平台实例"""
    if not pc.enabled:
        return
    platform_cls = get_platform_class(pc.platform)
    if platform_cls:
        instance = platform_cls(pc.get_config())
        # 标记配置ID，支持同一平台类型多实例
        instance._config_id = pc.id
        register_platform(instance)


@admin_config_bp.route("/platforms/schema/<platform_type>")
@admin_required
def platform_schema(platform_type):
    """返回指定平台的配置 Schema（用于 AJAX 动态渲染）"""
    platform_cls = get_platform_class(platform_type)
    if not platform_cls:
        return jsonify({"fields": []})
    schema = platform_cls({}).get_config_schema()
    return jsonify(schema)
