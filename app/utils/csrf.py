"""CSRF 防护工具

基于 SECRET_KEY 的 Stateless CSRF Token 实现。
Token = HMAC-SHA256(timestamp + random, SECRET_KEY)
有效期：2 小时
"""
import hmac
import base64
import hashlib
import os
import time
from flask import current_app, request, abort, jsonify


def _get_secret() -> str:
    return current_app.config.get("SECRET_KEY", "")


def generate_csrf_token() -> str:
    """生成 CSRF Token（stateless）"""
    secret = _get_secret()
    timestamp = str(int(time.time()))
    random = base64.b64encode(os.urandom(8)).decode("utf-8")
    msg = f"{timestamp}:{random}"
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{msg}:{sig}".encode("utf-8")).decode("utf-8")
    return token


def verify_csrf_token(token: str, max_age: int = 7200) -> bool:
    """验证 CSRF Token

    Args:
        token: CSRF Token 字符串
        max_age: 有效时间（秒），默认 2 小时
    """
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        parts = decoded.rsplit(":", 2)
        if len(parts) != 3:
            return False
        timestamp_str, random, sig_expected = parts
        # 检查过期
        try:
            ts = int(timestamp_str)
            if time.time() - ts > max_age:
                return False
        except ValueError:
            return False
        # 验证签名
        secret = _get_secret()
        msg = f"{timestamp_str}:{random}"
        sig_actual = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig_actual, sig_expected)
    except Exception:
        return False


def csrf_protected(f):
    """装饰器：对 POST 端点进行 CSRF 验证

    从以下位置获取 Token（按优先级）：
    1. HTTP Header X-CSRFToken
    2. 表单字段 csrf_token

    验证失败时 abort(403) 返回 HTML 错误页（适用于页面表单）。
    """
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "POST":
            token = request.headers.get("X-CSRFToken", "")
            if not token:
                token = request.form.get("csrf_token", "")
            if not verify_csrf_token(token):
                abort(403, description="CSRF token 无效或已过期")
        return f(*args, **kwargs)
    return decorated


def csrf_protected_json(f):
    """装饰器：对 POST 端点进行 CSRF 验证（返回 JSON）

    和 csrf_protected 功能相同，但验证失败时返回 JSON 响应
    而不是 HTML 错误页，适用于 AJAX / API 端点。
    """
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "POST":
            token = request.headers.get("X-CSRFToken", "")
            if not token:
                token = request.form.get("csrf_token", "")
            if not verify_csrf_token(token):
                return jsonify({"success": False, "message": "CSRF token 无效或已过期"}), 403
        return f(*args, **kwargs)
    return decorated
