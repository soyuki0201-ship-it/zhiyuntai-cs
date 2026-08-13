"""回归测试：api.py 的 UnboundLocalError: current_app

覆盖线上报错的真实代码路径（用 Flask test client 打真实 api 蓝图路由）：
- GET  /api/wechat_work/callback → 回调URL验证
- POST /api/wechat_work/callback → 企微消息推送（线上必崩）
"""
import os
import sys
import time
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------- 轻量 stub 重依赖，只测回调路由 ----------
import types
_stub_modules = {}
for _name in ("sentence_transformers", "paddleocr", "apscheduler"):
    _m = types.ModuleType(_name)
    _stub_modules[_name] = _m
    sys.modules[_name] = _m
# apscheduler 需要 BackgroundScheduler（app/__init__.py 会 from ... import init_scheduler）
_sched = types.ModuleType("apscheduler.schedulers")
_sched2 = types.ModuleType("apscheduler.schedulers.background")
class _FakeBackgroundScheduler:
    def start(self, *a, **k): pass
_sched2.BackgroundScheduler = _FakeBackgroundScheduler
_sched.background = _sched2
sys.modules["apscheduler.schedulers"] = _sched
sys.modules["apscheduler.schedulers.background"] = _sched2
# SentenceTransformer 类（vector_store 会引用）
class _FakeSentenceTransformer:
    def __init__(self, *a, **k): pass
    def encode(self, *a, **k):
        import numpy as np
        return np.zeros((1, 128), dtype="float32")
_stub_modules["sentence_transformers"].SentenceTransformer = _FakeSentenceTransformer
# ---------------------------------------------------

def _make_stub_platform():
    p = MagicMock()
    p.handle_verification.return_value = "verification ok"
    p.verify_request.return_value = True
    p.get_platform_type.return_value = "wechat_work"
    p._config_id = 1
    return p


def _call_route(method):
    from app.routes.api import api_bp
    from flask import Flask
    from app.utils.rate_limit import _windows

    _windows.clear()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test"
    app.register_blueprint(api_bp)

    stub = _make_stub_platform()
    with patch("app.routes.api.get_platform", return_value=stub), \
         patch("app.routes.api.process_unified_message") as mock_process:
        client = app.test_client()
        if method == "GET":
            r = client.get("/api/wechat_work/callback")
        else:
            r = client.post("/api/wechat_work/callback")
    return r, stub, mock_process


class TestPlatformCallbackUnboundLocalError:
    def test_get_verification_ok(self):
        """GET 回调URL验证应返回 200"""
        r, stub, _ = _call_route("GET")
        assert r.status_code == 200
        assert stub.handle_verification.called

    def test_post_message_pushes_to_thread(self):
        """POST 消息推送：通过验签→返回200→异步线程启动解析并处理，不得抛 UnboundLocalError"""
        r, stub, mock_process = _call_route("POST")
        assert r.status_code == 200, f"POST 应返回 200，实际 {r.status_code}"
        assert stub.verify_request.called, "必须先调用 verify_request 验签"
        time.sleep(0.3)
        assert stub.parse_message.called, "异步线程应已启动解析消息（若 UnboundLocalError 则不会走到这里）"
        assert mock_process.called, "业务处理应被调用"
