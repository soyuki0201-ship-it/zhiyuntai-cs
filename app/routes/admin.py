"""管理后台路由

架构设计文档 5.7「管理后台功能说明」：
- 全部对话列表（默认首页，支持按状态筛选）
- 待处理列表（快捷入口）
- 处理中列表
- 对话详情页（含接管/释放操作）
- 知识库管理
- 登录/退出
"""
import logging
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from app.models.models import db, Conversation, Message, Knowledge
from app.services.handoff_service import HandoffService
from app.services.knowledge_service import KnowledgeService
from app.utils.csrf import generate_csrf_token, csrf_protected

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Session 登录校验装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """管理后台登录页面"""
    if request.method == "POST":
        from flask import current_app
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if (username == current_app.config["ADMIN_USERNAME"] and
            password == current_app.config["ADMIN_PASSWORD"]):
            session["admin_logged_in"] = True
            session.permanent = True
            return redirect(url_for("admin.conversation_list"))
        return render_template("admin/login.html", error="用户名或密码错误")
    return render_template("admin/login.html", error=None)


@admin_bp.route("/logout")
def logout():
    """退出登录"""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin.login"))


@admin_bp.context_processor
def inject_csrf_token():
    """注入 CSRF Token 生成函数到所有模板"""
    return dict(csrf_token=generate_csrf_token)


@admin_bp.route("/")
@admin_bp.route("/conversations")
@admin_required
def conversation_list():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    query = Conversation.query
    if status_filter:
        query = query.filter(Conversation.status == status_filter)
    pagination = query.order_by(Conversation.updated_at.desc()).paginate(page=page, per_page=20, error_out=False)

    conv_list = []
    for conv in pagination.items:
        last_msg = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at.desc()).first()
        conv_list.append({
            "id": conv.id, "channel": conv.channel, "user_id": conv.user_id,
            "user_name": conv.user_name or conv.user_id,
            "group_name": conv.group_name or "",
            "status": conv.status,
            "last_message": last_msg.content[:100] if last_msg else "",
            "last_time": conv.updated_at,
        })
    return render_template("admin/conversations.html", conversations=conv_list, pagination=pagination, current_status=status_filter)


@admin_bp.route("/conversations/<int:conv_id>")
@admin_required
def conversation_detail(conv_id):
    conv = Conversation.query.get_or_404(conv_id)
    messages = Message.query.filter_by(conversation_id=conv_id).order_by(Message.created_at.asc()).all()
    is_handed_over = HandoffService.is_handed_over(conv.user_id)
    return render_template("admin/conversation_detail.html", conversation=conv, messages=messages, is_handed_over=is_handed_over)


@admin_bp.route("/takeover", methods=["POST"])
@admin_required
@csrf_protected
def takeover():
    user_id = request.form.get("user_id", "")
    if not user_id:
        return jsonify({"success": False, "message": "缺少 user_id"}), 400
    success = HandoffService.take_over(user_id)
    if success:
        return jsonify({"success": True, "message": "接管成功"})
    return jsonify({"success": False, "message": "接管失败：客户无活跃对话"})


@admin_bp.route("/release", methods=["POST"])
@admin_required
@csrf_protected
def release():
    user_id = request.form.get("user_id", "")
    if not user_id:
        return jsonify({"success": False, "message": "缺少 user_id"}), 400
    success = HandoffService.release(user_id)
    if success:
        return jsonify({"success": True, "message": "释放成功"})
    return jsonify({"success": False, "message": "释放失败：该客户未被接管"})


@admin_bp.route("/pending")
@admin_required
def pending_list():
    page = request.args.get("page", 1, type=int)
    query = Conversation.query.filter(Conversation.status.in_(["transferred"]))
    pagination = query.order_by(Conversation.updated_at.desc()).paginate(page=page, per_page=20, error_out=False)

    conv_list = []
    for conv in pagination.items:
        if HandoffService.is_handed_over(conv.user_id):
            continue
        last_msg = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at.desc()).first()
        conv_list.append({
            "id": conv.id, "channel": conv.channel, "user_id": conv.user_id,
            "user_name": conv.user_name or conv.user_id,
            "group_name": conv.group_name or "",
            "last_message": last_msg.content[:100] if last_msg else "",
            "last_time": conv.updated_at,
        })
    return render_template("admin/pending.html", conversations=conv_list, pagination=pagination)


@admin_bp.route("/active")
@admin_required
def active_list():
    page = request.args.get("page", 1, type=int)
    items, total = HandoffService.get_all_active(page=page, per_page=20)
    return render_template("admin/active.html", handoffs=items)


@admin_bp.route("/knowledge")
@admin_required
def knowledge_list():
    page = request.args.get("page", 1, type=int)
    items, total = KnowledgeService.list_all(page=page, per_page=20)
    return render_template("admin/knowledge_list.html", knowledge_list=items)


@admin_bp.route("/knowledge/add", methods=["GET", "POST"])
@admin_required
def knowledge_add():
    if request.method == "POST":
        title = request.form.get("title", "")
        content = request.form.get("content", "")
        source = request.form.get("source", "manual")
        tags = request.form.get("tags", "")
        category = request.form.get("category", "")
        if title and content:
            KnowledgeService.add(title, content, source=source, tags=tags, category=category or None)
            return redirect(url_for("admin.knowledge_list"))
    return render_template("admin/knowledge_form.html", knowledge=None)


@admin_bp.route("/knowledge/<int:kid>/edit", methods=["GET", "POST"])
@admin_required
def knowledge_edit(kid):
    knowledge = Knowledge.query.get_or_404(kid)
    if request.method == "POST":
        title = request.form.get("title", "")
        content = request.form.get("content", "")
        tags = request.form.get("tags", "")
        category = request.form.get("category", "")
        if title and content:
            KnowledgeService.update(kid, title=title, content=content, tags=tags, category=category or None)
            return redirect(url_for("admin.knowledge_list"))
    return render_template("admin/knowledge_form.html", knowledge=knowledge)


@admin_bp.route("/knowledge/<int:kid>/delete", methods=["POST"])
@admin_required
@csrf_protected
def knowledge_delete(kid):
    KnowledgeService.delete(kid)
    return redirect(url_for("admin.knowledge_list"))
