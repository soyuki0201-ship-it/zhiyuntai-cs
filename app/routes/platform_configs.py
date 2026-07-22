"""管理后台路由 - 平台配置

新增【平台配置】菜单，支持动态管理所有IM平台的接入信息。
"""
import json
import logging
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app import auth
from app.models.platform_config import PlatformConfig
from app.models import db
from app.core.platform_manager import get_platform_class, register_platform

logger = logging.getLogger(__name__)
admin_config_bp = Blueprint("admin_config", __name__, url_prefix="/admin")


@admin_config_bp.route("/platforms")
@auth.login_required
def platform_list():
    """平台配置列表"""
    configs = PlatformConfig.query.order_by(PlatformConfig.platform).all()
    return render_template("admin/platform_list.html", configs=configs)


@admin_config_bp.route("/platforms/add", methods=["GET", "POST"])
@auth.login_required
def platform_add():
    """新增平台配置"""
    if request.method == "POST":
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
            config_json=config_json,
        )
        db.session.add(pc)
        db.session.commit()

        # 动态注册平台实例
        _register_platform_from_config(pc)

        return redirect(url_for("admin_config.platform_list"))

    # GET: 展示可用的平台类型
    available = [
        {"type": "wechat_work", "name": "企业微信"},
    ]
    return render_template("admin/platform_form.html", config=None, available=available)


@admin_config_bp.route("/platforms/<int:pid>/edit", methods=["GET", "POST"])
@auth.login_required
def platform_edit(pid):
    """编辑平台配置"""
    pc = PlatformConfig.query.get_or_404(pid)

    if request.method == "POST":
        pc.name = request.form.get("name", pc.name)
        pc.enabled = request.form.get("enabled", "1") == "1"

        # 更新配置项
        config_json = {}
        platform_cls = get_platform_class(pc.platform)
        if platform_cls:
            schema = platform_cls({}).get_config_schema()
            for field in schema.get("fields", []):
                key = field["key"]
                value = request.form.get(f"cfg_{key}", "")
                if value:
                    config_json[key] = value

        pc.config_json = config_json
        db.session.commit()

        # 重新注册
        _register_platform_from_config(pc)

        return redirect(url_for("admin_config.platform_list"))

    platform_cls = get_platform_class(pc.platform)
    schema = platform_cls({}).get_config_schema() if platform_cls else {"fields": []}

    return render_template("admin/platform_form.html", config=pc, available=[], schema=schema)


@admin_config_bp.route("/platforms/<int:pid>/delete", methods=["POST"])
@auth.login_required
def platform_delete(pid):
    """删除平台配置"""
    pc = PlatformConfig.query.get_or_404(pid)
    db.session.delete(pc)
    db.session.commit()
    return redirect(url_for("admin_config.platform_list"))


@admin_config_bp.route("/platforms/<int:pid>/test", methods=["POST"])
@auth.login_required
def platform_test(pid):
    """测试平台连接"""
    pc = PlatformConfig.query.get_or_404(pid)
    platform_cls = get_platform_class(pc.platform)
    if not platform_cls:
        return jsonify({"success": False, "message": "未知平台类型"})

    instance = platform_cls(pc.config_json)
    result = instance.test_connection(pc.config_json)
    return jsonify(result)


def _register_platform_from_config(pc: PlatformConfig):
    """根据数据库配置注册平台实例"""
    if not pc.enabled:
        return
    platform_cls = get_platform_class(pc.platform)
    if platform_cls:
        instance = platform_cls(pc.config_json)
        register_platform(instance)
