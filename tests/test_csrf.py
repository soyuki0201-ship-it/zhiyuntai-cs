"""CSRF 工具单元测试

覆盖：token 生成、有效校验、篡改拒绝、过期拒绝、无 token 拒绝。
"""
import time
from app.utils.csrf import generate_csrf_token, verify_csrf_token


def _make_token(secret, timestamp, random):
    """构造指定时间戳和随机串的 token（用于过期测试）"""
    import hmac
    import base64
    import hashlib
    msg = f"{timestamp}:{random}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}:{sig}".encode()).decode()


class TestCSRFToken:
    def test_generate_returns_string(self, app):
        with app.app_context():
            token = generate_csrf_token()
        assert isinstance(token, str)
        assert len(token) > 10

    def test_valid_token_passes(self, app):
        with app.app_context():
            token = generate_csrf_token()
            assert verify_csrf_token(token) is True

    def test_tampered_token_rejected(self, app):
        with app.app_context():
            token = generate_csrf_token()
            # 篡改最后一个字符
            tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
            assert verify_csrf_token(tampered) is False

    def test_empty_token_rejected(self, app):
        with app.app_context():
            assert verify_csrf_token("") is False
            assert verify_csrf_token(None) is False

    def test_expired_token_rejected(self, app):
        with app.app_context():
            # 构造 3 小时前的 token（默认有效期 2 小时）
            old_ts = int(time.time()) - 3 * 3600
            token = _make_token("test-secret-key", old_ts, "abc123")
            assert verify_csrf_token(token) is False

    def test_garbage_token_rejected(self, app):
        with app.app_context():
            assert verify_csrf_token("!!!not-a-token!!!") is False
