"""AI 配置管理路由

管理后台 AI 配置页面：
- 大模型配置（多模型管理、主模型/备用）
- 对话参数
- 提示词
- 知识库检索参数
"""
import json
import logging
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from app.models.models import db, AIProvider, AIConfig
from app.utils.csrf import generate_csrf_token, csrf_protected

logger = logging.getLogger(__name__)
ai_config_bp = Blueprint("ai_config", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@ai_config_bp.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf_token)


@ai_config_bp.route("/ai-config")
@admin_required
def ai_config_page():
    """AI 配置页面"""
    providers = AIProvider.query.order_by(AIProvider.sort_order).all()
    config = AIConfig.query.first()
    if not config:
        config = _init_default_config()
    # 解密API Key用于编辑回显
    decrypted = []
    for p in providers:
        p_data = {"id": p.id, "name": p.name, "provider": p.provider,
                   "model_name": p.model_name, "api_url": p.api_url,
                   "is_primary": p.is_primary, "enabled": p.enabled,
                   "sort_order": p.sort_order}
        decrypted.append(p_data)
    return render_template("admin/ai_config.html", providers=decrypted, config=config)


# ---- AI Providers CRUD ----

@ai_config_bp.route("/ai-config/providers/add", methods=["POST"])
@admin_required
@csrf_protected
def ai_provider_add():
    name = request.form.get("name", "")
    provider = request.form.get("provider", "")
    model_name = request.form.get("model_name", "")
    api_url = request.form.get("api_url", "")
    api_key = request.form.get("api_key", "")
    is_primary = request.form.get("is_primary", "0") == "1"
    enabled = request.form.get("enabled", "1") == "1"

    if not all([name, provider, model_name, api_url, api_key]):
        return jsonify({"success": False, "message": "请填写必填字段"}), 400

    if is_primary:
        # 将其他模型的is_primary设为False
        AIProvider.query.filter_by(is_primary=True).update({"is_primary": False})

    p = AIProvider(name=name, provider=provider, model_name=model_name,
                   api_url=api_url, api_key=api_key, is_primary=is_primary,
                   enabled=enabled, sort_order=0 if is_primary else 99)
    db.session.add(p)
    db.session.commit()
    return jsonify({"success": True, "message": "模型已添加"})


@ai_config_bp.route("/ai-config/providers/<int:pid>/edit", methods=["POST"])
@admin_required
@csrf_protected
def ai_provider_edit(pid):
    p = AIProvider.query.get_or_404(pid)
    p.name = request.form.get("name", p.name)
    p.provider = request.form.get("provider", p.provider)
    p.model_name = request.form.get("model_name", p.model_name)
    p.api_url = request.form.get("api_url", p.api_url)
    api_key = request.form.get("api_key", "")
    if api_key:
        p.api_key = api_key
    p.enabled = request.form.get("enabled", "1") == "1"

    is_primary = request.form.get("is_primary", "0") == "1"
    if is_primary:
        AIProvider.query.filter(AIProvider.id != pid, AIProvider.is_primary == True).update({"is_primary": False})
        p.is_primary = True
        p.sort_order = 0

    db.session.commit()
    return jsonify({"success": True, "message": "模型已更新"})


@ai_config_bp.route("/ai-config/providers/<int:pid>/delete", methods=["POST"])
@admin_required
@csrf_protected
def ai_provider_delete(pid):
    p = AIProvider.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return jsonify({"success": True, "message": "模型已删除"})


@ai_config_bp.route("/ai-config/providers/<int:pid>/test", methods=["POST"])
@admin_required
def ai_provider_test(pid):
    """测试AI模型连接"""
    p = AIProvider.query.get_or_404(pid)
    try:
        from app.services.ai_service import test_provider_connection
        result = test_provider_connection(p.api_url, p.api_key, p.model_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@ai_config_bp.route("/ai-config/providers/<int:pid>/set-primary", methods=["POST"])
@admin_required
@csrf_protected
def ai_provider_set_primary(pid):
    AIProvider.query.filter_by(is_primary=True).update({"is_primary": False})
    p = AIProvider.query.get_or_404(pid)
    p.is_primary = True
    p.sort_order = 0
    db.session.commit()
    return jsonify({"success": True, "message": f"已设 {p.name} 为主模型"})


# ---- AI System Config ----

@ai_config_bp.route("/ai-config/config", methods=["POST"])
@admin_required
@csrf_protected
def ai_system_config_save():
    config = AIConfig.query.first()
    if not config:
        config = _init_default_config()

    config.ai_name = request.form.get("ai_name", "智云台助手")
    config.temperature = float(request.form.get("temperature", 0.7))
    config.max_tokens = int(request.form.get("max_tokens", 2000))
    config.max_history_rounds = int(request.form.get("max_history_rounds", 10))
    config.system_prompt = request.form.get("system_prompt", "")
    config.handoff_markers = request.form.get("handoff_markers", "")
    config.rag_top_k = int(request.form.get("rag_top_k", 5))
    config.rag_similarity_threshold = float(request.form.get("rag_similarity_threshold", 0.6))
    db.session.commit()
    return jsonify({"success": True, "message": "对话参数已保存"})


def _init_default_config():
    """初始化默认AI配置"""
    from app.services.prompt_builder import PromptBuilder
    config = AIConfig(
        ai_name="智云台助手",
        system_prompt=PromptBuilder.SYSTEM_PROMPT,
        temperature=0.7,
        max_tokens=2000,
        max_history_rounds=10,
        handoff_markers=",".join(PromptBuilder.handoff_markers),
        rag_top_k=5,
        rag_similarity_threshold=0.6,
    )
    db.session.add(config)
    db.session.commit()
    return config
