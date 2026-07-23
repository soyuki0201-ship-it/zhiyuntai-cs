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
import csv
import io
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, Response
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
    """注入 CSRF Token 和待处理数量到所有模板"""
    pending_count = 0
    try:
        pending_count = HandoffService.get_pending_count()
    except Exception:
        pass
    return dict(csrf_token=generate_csrf_token, pending_count=pending_count)


@admin_bp.route("/")
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    """工作台首页"""
    from datetime import datetime, timedelta
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Message.query.filter(Message.created_at >= today_start).count()
    ai_count = Message.query.filter(Message.created_at >= today_start, Message.role == "assistant").count()
    handoff_count = Handoff.query.filter(Handoff.taken_at >= today_start).count()
    return render_template("admin/dashboard.html",
        today_count=today_count,
        ai_count=ai_count,
        handoff_count=handoff_count,
    )


@admin_bp.route("/conversations")
@admin_required
def conversation_list():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    search_query = request.args.get("q", "").strip()
    query = Conversation.query
    if status_filter:
        query = query.filter(Conversation.status == status_filter)
    if search_query:
        pattern = f"%{search_query}%"
        query = query.filter(
            db.or_(Conversation.user_name.like(pattern), Conversation.user_id.like(pattern))
        )
    pagination = query.order_by(Conversation.updated_at.desc()).paginate(page=page, per_page=20, error_out=False)
    total_count = Conversation.query.count()

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
    return render_template("admin/conversations.html", conversations=conv_list, pagination=pagination, current_status=status_filter, total_count=total_count)


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

    items, total = HandoffService.get_all_active(page=1, per_page=100)
    return render_template("admin/pending.html", conversations=conv_list, handoffs=items, pagination=pagination, active_count=total)


@admin_bp.route("/knowledge")
@admin_required
def knowledge_list():
    page = request.args.get("page", 1, type=int)
    search_query = request.args.get("q", "").strip()
    if search_query:
        items, total, pagination = KnowledgeService.search_by_title(search_query, page=page, per_page=20)
    else:
        items, total, pagination = KnowledgeService.list_all(page=page, per_page=20)

    # 本月新增统计
    from datetime import datetime, timedelta
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_new = Knowledge.query.filter(Knowledge.created_at >= month_start).count()

    return render_template("admin/knowledge_list.html", knowledge_list=items, knowledge_total=total, monthly_new=monthly_new, search_query=search_query, page=page, pagination=pagination)


@admin_bp.route("/knowledge/add", methods=["GET", "POST"])
@admin_required
@csrf_protected
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
@csrf_protected
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


# 知识库批量导入的合法分类列表
VALID_CATEGORIES = {"产品功能介绍", "产品常见问题", "产品使用教程", "付费相关", "故障处理", "需求提出", "其他"}


@admin_bp.route("/knowledge/import", methods=["GET", "POST"])
@admin_required
def knowledge_import():
    """知识库批量导入页面"""
    if request.method == "POST":
        # CSRF 验证（因为前端用 fetch + FormData 提交）
        token = request.form.get("csrf_token", "")
        from app.utils.csrf import verify_csrf_token
        if not verify_csrf_token(token):
            return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403

        file = request.files.get("file", None)
        if not file or not file.filename:
            return jsonify({"success": False, "message": "请选择要上传的 CSV 文件"})

        try:
            content = file.read()
            # 尝试自动检测编码：优先 UTF-8，其次 GBK
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("gbk")

            reader = csv.DictReader(io.StringIO(text))
            total = 0
            success = 0
            errors = []

            for idx, row in enumerate(reader, start=2):  # 从第2行开始（第1行是表头）
                total += 1
                title = (row.get("title") or "").strip()
                content_text = (row.get("content") or "").strip()
                category = (row.get("category") or "").strip()
                tags = (row.get("tags") or "").strip()

                if not title or not content_text:
                    errors.append(f"第{idx}行：标题或内容为空")
                    continue

                if category and category not in VALID_CATEGORIES:
                    errors.append(f"第{idx}行：分类「{category}」不在合法范围内")
                    continue

                try:
                    KnowledgeService.add(
                        title=title,
                        content=content_text,
                        source="batch_import",
                        tags=tags if tags else None,
                        category=category if category else None,
                    )
                    success += 1
                except Exception as e:
                    errors.append(f"第{idx}行：导入失败 - {str(e)}")

            return jsonify({
                "success": True,
                "total": total,
                "success_count": success,
                "fail_count": len(errors),
                "errors": errors,
            })

        except Exception as e:
            return jsonify({"success": False, "message": f"文件解析失败：{str(e)}"})

    return render_template("admin/knowledge_import.html")


@admin_bp.route("/knowledge/import/template")
@admin_required
def knowledge_import_template():
    """下载 CSV 导入模板"""
    output = io.StringIO()
    output.write("﻿")  # UTF-8 with BOM
    writer = csv.writer(output)
    writer.writerow(["title", "content", "category", "tags"])
    writer.writerow(["测略功能介绍", "测略功能是分析投放数据的工具，支持多维度筛选和导出。", "产品功能介绍", "测略,功能介绍"])
    writer.writerow(["企业微信接入常见问题", "问题：支持企业微信吗？答案：支持企业微信。", "产品常见问题", "企业微信,接入"])
    writer.writerow(["靓号插件使用教程", "第一步：安装插件\n第二步：登录账号\n第三步：开始使用", "产品使用教程", "靓号,教程"])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=知识库导入模板.csv"},
    )


@admin_bp.route("/settings")
@admin_required
def settings_page():
    """系统设置页面"""
    from flask import current_app
    return render_template("admin/settings.html",
        admin_username=current_app.config.get("ADMIN_USERNAME", "admin"),
        conversation_ttl=current_app.config.get("CONVERSATION_TTL_DAYS", 30),
        handoff_timeout=current_app.config.get("HANDOFF_TIMEOUT_MINUTES", 30),
    )


@admin_bp.route("/settings/save", methods=["POST"])
@admin_required
@csrf_protected
def settings_save():
    """保存系统设置"""
    from flask import current_app
    conversation_ttl = request.form.get("conversation_ttl", "").strip()
    handoff_timeout = request.form.get("handoff_timeout", "").strip()

    if conversation_ttl:
        try:
            current_app.config["CONVERSATION_TTL_DAYS"] = int(conversation_ttl)
        except ValueError:
            return jsonify({"success": True, "message": "对话保留天数格式无效，保留原值"})

    if handoff_timeout:
        try:
            current_app.config["HANDOFF_TIMEOUT_MINUTES"] = int(handoff_timeout)
        except ValueError:
            return jsonify({"success": True, "message": "接管超时时间格式无效，保留原值"})

    return jsonify({"success": True, "message": "设置已保存（重启后重新加载 .env 变更）"})
