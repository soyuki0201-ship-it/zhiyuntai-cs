"""企微自建应用 回调边界场景测试

覆盖真实路由的各种输入边界：
- GET 验证成功 / 失败
- POST 验签失败 / 畸形XML / 空body
- 未知平台 404
- 限速 429
- 图片消息（无MediaId优雅降级）
- 特殊字符内容（XML CDATA 转义）
- 长消息
"""
import os
import sys
import time
import types
import hashlib
import struct
import base64

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------- 轻量 stub 重依赖 ----------
for _name in ("sentence_transformers", "paddleocr", "apscheduler"):
    _m = types.ModuleType(_name)
    sys.modules[_name] = _m
class _FakeBackgroundScheduler:
    def start(self, *a, **k): pass
_s = types.ModuleType("apscheduler.schedulers")
_s2 = types.ModuleType("apscheduler.schedulers.background")
_s2.BackgroundScheduler = _FakeBackgroundScheduler
_s.background = _s2
sys.modules["apscheduler.schedulers"] = _s
sys.modules["apscheduler.schedulers.background"] = _s2
class _FakeST:
    def __init__(self, *a, **k): pass
    def encode(self, *a, **k):
        import numpy as np
        return np.zeros((1, 128), dtype="float32")
sys.modules["sentence_transformers"].SentenceTransformer = _FakeST

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

REAL_TOKEN = "FIlSYOeyUIbxGdJ71dfEHhWE1NHP6"
REAL_AES_KEY = "o82DPywEqN72TznzsoZui2pmdQwXzBa4Xr31Ee3pghz"
REAL_CORP_ID = "wwdb0952725fbeeb19"


def _encrypt_space_pad(plain_xml, aes_key, receive_id):
    """企微式空格padding加密"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    mb = plain_xml.encode("utf-8")
    body = os.urandom(16) + struct.pack(">I", len(mb)) + mb + receive_id.encode("utf-8")
    pad = 16 - (len(body) % 16)
    padded = body + b"\x20" * pad
    c = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    e = c.encryptor()
    return base64.b64encode(e.update(padded) + e.finalize()).decode()


def _sign(token, timestamp, nonce, msg):
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, msg])).encode()).hexdigest()


def _text_xml(content, from_user="19147955655", msg_id="7673077215275977819", msg_type="text"):
    return (f"<xml><ToUserName><![CDATA[{REAL_CORP_ID}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>1786529844</CreateTime>"
            f"<MsgType><![CDATA[{msg_type}]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content>"
            f"<MsgId>{msg_id}</MsgId>"
            f"<AgentID>1000037</AgentID></xml>")


def _build_post(plain_xml, token=REAL_TOKEN, ts="1786529844", nonce="1786724575",
                correct_sig=True, aes_key=None):
    key = base64.b64decode((aes_key or REAL_AES_KEY) + "=")
    enc = _encrypt_space_pad(plain_xml, key, REAL_CORP_ID)
    sig = _sign(token, ts, nonce, enc) if correct_sig else "deadbeef" * 5
    body = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>".encode("utf-8")
    return f"/api/wechat_work/callback?msg_signature={sig}&timestamp={ts}&nonce={nonce}", body


@pytest.fixture
def app():
    from app.routes.api import api_bp
    from app.platforms.wechat_work import WeChatWorkPlatform
    from app.core.platform_manager import register_platform, _platforms
    from app.utils.rate_limit import _windows

    _platforms.clear()
    _windows.clear()
    p = WeChatWorkPlatform(config={
        "corp_id": REAL_CORP_ID,
        "token": REAL_TOKEN,
        "encoding_aes_key": REAL_AES_KEY,
    })
    p._config_id = 1
    register_platform(p)

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test"
    flask_app.register_blueprint(api_bp)
    return flask_app


class TestWeChatWorkBoundary:
    # ---------- GET 验证 ----------
    def test_get_verification_success(self, app):
        """GET 回调URL验证：合法 echostr → 200 + 解密明文"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        crypto = None
        from app.platforms.wechat_work.crypto import WecomMsgCrypto
        crypto = WecomMsgCrypto(REAL_TOKEN, REAL_AES_KEY, REAL_CORP_ID)
        key = base64.b64decode(REAL_AES_KEY + "=")
        echo_plain = "random_echo_string_12345"
        # 构造 echostr（明文=echo，企微式加密）
        mb = echo_plain.encode()
        body = os.urandom(16) + struct.pack(">I", len(mb)) + mb + REAL_CORP_ID.encode()
        pad = 16 - (len(body) % 16)
        padded = body + b"\x20" * pad
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        c = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
        e = c.encryptor()
        echostr = base64.b64encode(e.update(padded) + e.finalize()).decode()
        ts, nonce = "1786529844", "1786724575"
        sig = _sign(REAL_TOKEN, ts, nonce, echostr)
        from urllib.parse import urlencode
        client = app.test_client()
        # echostr/sig 是 base64，含 + / = 等字符，必须 URL 编码（直接拼串 + 会被解析成空格 → 签名失败）
        query = urlencode({"msg_signature": sig, "timestamp": ts, "nonce": nonce, "echostr": echostr})
        r = client.get(f"/api/wechat_work/callback?{query}")
        assert r.status_code == 200, f"期望200，实际 {r.status_code}: {r.data}"
        assert r.data.decode() == echo_plain, f"应返回解密明文，实际 {r.data}"

    def test_get_verification_bad_signature(self, app):
        """GET 验证：坏签名 → 403"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        client = app.test_client()
        r = client.get("/api/wechat_work/callback?msg_signature=bad&timestamp=1&nonce=2&echostr=xyz")
        assert r.status_code == 403
        assert b"verification failed" in r.data

    def test_get_unknown_platform(self, app):
        """GET 未知平台 → 404"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        client = app.test_client()
        r = client.get("/api/feishu/callback")
        assert r.status_code == 404
        assert b"platform not found" in r.data

    # ---------- POST 异常输入 ----------
    def test_post_bad_signature_403(self, app):
        """POST 验签失败 → 403"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        path, body = _build_post(_text_xml("hi"), correct_sig=False)
        client = app.test_client()
        r = client.post(path, data=body, content_type="text/xml")
        assert r.status_code == 403
        assert b"invalid request" in r.data

    def test_post_malformed_xml_403(self, app):
        """POST 畸形XML（不是合法XML）→ 验签失败 403"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        client = app.test_client()
        # 直接发非XML内容，无法通过验签
        r = client.post("/api/wechat_work/callback?msg_signature=bad&timestamp=1&nonce=2",
                        data=b"not xml at all", content_type="text/xml")
        assert r.status_code == 403

    def test_post_empty_body_403(self, app):
        """POST 空body → 403"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        client = app.test_client()
        r = client.post("/api/wechat_work/callback?msg_signature=bad&timestamp=1&nonce=2",
                        data=b"", content_type="text/xml")
        assert r.status_code == 403

    def test_post_valid_message_200(self, app):
        """POST 合法消息 → 200 + 异步线程处理"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        path, body = _build_post(_text_xml("边界测试消息"))
        with patch("app.routes.api.process_unified_message") as mp:
            client = app.test_client()
            r = client.post(path, data=body, content_type="text/xml")
            assert r.status_code == 200
            time.sleep(0.5)
            assert mp.called, "合法消息应进入异步处理"

    # ---------- 限速 ----------
    def test_rate_limit_429(self, app):
        """同IP超60次/分钟 → 429"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        client = app.test_client()
        # 60 次坏请求（每次返回403，但计入限速）
        for _ in range(60):
            client.get("/api/wechat_work/callback?msg_signature=bad&timestamp=1&nonce=2&echostr=x")
        # 第61次 → 429
        r = client.get("/api/wechat_work/callback?msg_signature=bad&timestamp=1&nonce=2&echostr=x")
        assert r.status_code == 429

    # ---------- 内容边界 ----------
    def test_special_chars_content(self, app):
        """内容含 XML 特殊字符（< > &）→ 正常解析"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        content = "你好 <b>加粗</b> & 测试 > 号"
        path, body = _build_post(_text_xml(content))
        with patch("app.routes.api.process_unified_message") as mp:
            client = app.test_client()
            r = client.post(path, data=body, content_type="text/xml")
            assert r.status_code == 200
            time.sleep(0.5)
            assert mp.called
            msg = mp.call_args[0][0]
            assert msg.content == content, f"内容应原样保留，实际 {msg.content!r}"

    def test_image_message_no_media(self, app):
        """图片消息无 MediaId → 优雅降级 [图片]（未能识别）"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        xml = (f"<xml><ToUserName><![CDATA[{REAL_CORP_ID}]]></ToUserName>"
               f"<FromUserName><![CDATA[19147955655]]></FromUserName>"
               f"<MsgType><![CDATA[image]]></MsgType>"
               f"<Content><![CDATA[]]></Content>"
               f"<MsgId>888</MsgId><AgentID>1000037</AgentID></xml>")
        path, body = _build_post(xml)
        with patch("app.routes.api.process_unified_message") as mp:
            client = app.test_client()
            r = client.post(path, data=body, content_type="text/xml")
            assert r.status_code == 200
            time.sleep(0.5)
            assert mp.called, "图片消息应进入异步处理（parse 内部降级，不崩溃）"
            msg = mp.call_args[0][0]
            assert "[图片]" in msg.content, f"应降级为图片提示，实际 {msg.content!r}"
            assert msg.msg_type == "text"  # 统一后转为 text

    def test_long_message_content(self, app):
        """长消息（>1KB）→ 正常解析"""
        from app.utils.rate_limit import _windows
        _windows.clear()
        content = "长消息" * 200  # 800 字
        path, body = _build_post(_text_xml(content))
        with patch("app.routes.api.process_unified_message") as mp:
            client = app.test_client()
            r = client.post(path, data=body, content_type="text/xml")
            assert r.status_code == 200
            time.sleep(0.5)
            assert mp.called
            msg = mp.call_args[0][0]
            assert msg.content == content
            assert len(msg.content) == len(content)
