"""回调限速工具单元测试

验证：滑动窗口计数，超限返回 429。
"""
import time
import pytest
from app.utils.rate_limit import rate_limit, _windows
from flask import Flask, Blueprint


@pytest.fixture(autouse=True)
def _reset_windows():
    """每个测试前清空限速窗口，避免测试间状态泄漏"""
    _windows.clear()
    yield
    _windows.clear()


def _make_app(limit, window):
    from flask import Response
    app = Flask(__name__)
    bp = Blueprint("test_limits", __name__)

    @bp.route("/cb", methods=["GET"])
    @rate_limit(max_requests=limit, window_seconds=window)
    def cb():
        return Response("ok", status=200)

    app.register_blueprint(bp)
    return app


class TestRateLimit:
    def test_under_limit_passes(self):
        app = _make_app(limit=3, window=60)
        with app.test_client() as c:
            for _ in range(3):
                r = c.get("/cb")
                assert r.status_code == 200

    def test_over_limit_returns_429(self):
        app = _make_app(limit=3, window=60)
        with app.test_client() as c:
            for _ in range(3):
                assert c.get("/cb").status_code == 200
            # 第 4 次超限
            r = c.get("/cb")
            assert r.status_code == 429

    def test_window_expires(self):
        app = _make_app(limit=2, window=1)  # 1 秒窗口
        with app.test_client() as c:
            assert c.get("/cb").status_code == 200
            assert c.get("/cb").status_code == 200
            assert c.get("/cb").status_code == 429  # 超限
            time.sleep(1.1)  # 等窗口过期
            assert c.get("/cb").status_code == 200  # 恢复
