"""企微自建应用 全链路端到端回归测试

覆盖线上完整链路（真实代码路径，不 mock 平台本身）：
  企微POST → 真实路由 platform_callback → verify_request(真实验签+空格padding解密)
  → 异步线程 → parse_message(真实解析) → process_unified_message(mock业务)

核心价值：
1. 防止 api.py 的 UnboundLocalError 回归（POST 必须能走到异步线程）
2. 防止 padding/receive_id 修复回归（真实企微格式密文必须能解开）
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

# 抓包真实配置
REAL_TOKEN = "FIlSYOeyUIbxGdJ71dfEHhWE1NHP6"
REAL_AES_KEY = "o82DPywEqN72TznzsoZui2pmdQwXzBa4Xr31Ee3pghz"
REAL_CORP_ID = "wwdb0952725fbeeb19"

REAL_XML = ("<xml><ToUserName><![CDATA[wwdb0952725fbeeb19]]></ToUserName>"
            "<FromUserName><![CDATA[19147955655]]></FromUserName>"
            "<CreateTime>1786529844</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[111]]></Content>"
            "<MsgId>7673077215275977819</MsgId>"
            "<AgentID>1000037</AgentID></xml>")


def _wecom_encrypt_space_pad(plain_xml, aes_key, receive_id):
    """按企微实际方式加密：空格(0x20)填充到16字节倍数"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    msg_bytes = plain_xml.encode("utf-8")
    body = os.urandom(16) + struct.pack(">I", len(msg_bytes)) + msg_bytes + receive_id.encode("utf-8")
    pad_len = 16 - (len(body) % 16)
    padded = body + b"\x20" * pad_len
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    enc = cipher.encryptor()
    return base64.b64encode(enc.update(padded) + enc.finalize()).decode("utf-8")


def _sign(token, timestamp, nonce, encrypt_text):
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypt_text])).encode()).hexdigest()


@pytest.fixture
def app():
    """注册真实 wechat_work 平台的 Flask 应用"""
    from app.routes.api import api_bp
    from app.platforms.wechat_work import WeChatWorkPlatform
    from app.core.platform_manager import register_platform, _platforms

    _platforms.clear()  # 避免测试间状态污染
    platform = WeChatWorkPlatform(config={
        "corp_id": REAL_CORP_ID,
        "token": REAL_TOKEN,
        "encoding_aes_key": REAL_AES_KEY,
    })
    platform._config_id = 1  # 生产环境由 app/__init__.py:112 在注册时设置
    register_platform(platform)

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test"
    flask_app.register_blueprint(api_bp)
    return flask_app


class TestWeChatWorkE2E:
    def test_post_real_wecom_message_full_pipeline(self, app):
        """真实企微格式消息 POST：验签→解密→异步线程→解析→业务处理"""
        from app.utils.rate_limit import _windows
        _windows.clear()

        aes_key = base64.b64decode(REAL_AES_KEY + "=")
        encrypt_text = _wecom_encrypt_space_pad(REAL_XML, aes_key, REAL_CORP_ID)
        ts, nonce = "1786529844", "1786724575"
        sig = _sign(REAL_TOKEN, ts, nonce, encrypt_text)
        body = f"<xml><Encrypt><![CDATA[{encrypt_text}]]></Encrypt></xml>".encode("utf-8")

        # process_unified_message 用 mock（不依赖 MySQL/模型），但 parse_message 走真实代码
        with patch("app.routes.api.process_unified_message") as mock_process:
            client = app.test_client()
            r = client.post(
                f"/api/wechat_work/callback?msg_signature={sig}&timestamp={ts}&nonce={nonce}",
                data=body,
                content_type="text/xml",
            )
            assert r.status_code == 200, f"POST 应返回 200，实际 {r.status_code}"

            # 异步线程是 daemon，给时间让它 parse + process
            time.sleep(0.4)
            assert mock_process.called, "业务处理应被异步线程调用（若 UnboundLocalError 则不会走到）"

        # 验证异步线程内 parse 的真实结果：直接调用一次 parse 验证解析正确
        from app.core.platform_manager import get_platform
        platform = get_platform("wechat_work")
        from werkzeug.wrappers import Request
        from werkzeug.test import EnvironBuilder
        b = EnvironBuilder(method="POST",
                           path=f"/callback?msg_signature={sig}&timestamp={ts}&nonce={nonce}",
                           data=body)
        env = b.get_environ()
        msg = platform.parse_message(Request(env))
        assert msg.content == "111"
        assert msg.user_id == "19147955655"
        assert msg.msg_type == "text"
        assert msg.msg_id == "7673077215275977819"
