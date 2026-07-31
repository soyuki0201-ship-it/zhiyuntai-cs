"""pytest 共享 fixture

测试不需要真实 MySQL，使用 Flask test client + 内存级依赖隔离。
对纯逻辑模块（csrf/rate_limit/模板渲染/注册顺序）做单元级验证。
"""
import os
import sys
import pytest

# 确保可以 import app 包（仅用于模板路径解析，不真正连数据库）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def app():
    """创建一个最小 Flask app（不初始化数据库/不注册完整蓝图）"""
    from flask import Flask
    flask_app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))
    flask_app.config.update(
        SECRET_KEY="test-secret-key",
        TESTING=True,
    )
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
