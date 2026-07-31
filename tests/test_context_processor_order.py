"""context_processor 注册顺序测试

验证：Flask 2.3+ 下，blueprint 的 context_processor 必须在 register_blueprint
之前注册，否则抛 AssertionError 且注入变量失效 → 页面 500。
对应修复：git 仓库 app/__init__.py 中 _register_admin_context_processors 调整到
register_blueprint 之前。
"""
import pytest
from flask import Blueprint, render_template_string

TEMPLATE = """<html><body>{% if pending_count > 0 %}badge:{{ pending_count }}{% else %}no-badge{% endif %}</body></html>"""


def _make_app(register_order):
    """register_order: 'before' 表示先注册 context_processor 再 register_blueprint
    'after' 表示先 register_blueprint 再注册 context_processor（错误顺序）
    """
    from flask import Flask
    app = Flask(__name__)

    bp = Blueprint(f"admin_{register_order}", __name__, url_prefix=f"/admin_{register_order}")

    @bp.route("/")
    def index():
        return render_template_string(TEMPLATE)

    if register_order == "before":
        # 正确：先注册 context_processor，再注册 blueprint
        bp.context_processor(lambda: dict(pending_count=5))
        app.register_blueprint(bp)
        error = None
    else:
        # 错误：先注册 blueprint，再注册 context_processor
        app.register_blueprint(bp)
        try:
            bp.context_processor(lambda: dict(pending_count=5))
            error = None
        except AssertionError as e:
            error = e

    return app, error


class TestContextProcessorOrder:
    def test_register_before_context_processor_ok(self):
        """context_processor 在 register_blueprint 之前注册 → 页面 200"""
        app, error = _make_app("before")
        assert error is None
        with app.test_client() as c:
            r = c.get("/admin_before/")
            assert r.status_code == 200
            assert "badge:5" in r.get_data(as_text=True)

    def test_register_after_context_processor_raises(self):
        """context_processor 在 register_blueprint 之后注册 → 抛 AssertionError"""
        app, error = _make_app("after")
        assert error is not None
        assert isinstance(error, AssertionError)
        # 且页面 500（变量未注入）
        with app.test_client() as c:
            r = c.get("/admin_after/")
            assert r.status_code == 500

    def test_online_init_order_matches_fixed(self):
        """线上版本 __init__.py 的顺序必须是 context_processor 先于 register_blueprint"""
        import ast
        import os
        init_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "__init__.py",
        )
        with open(init_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # 提取 create_app 函数体内的方法调用顺序
        register_line = None
        context_processor_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_app":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        if isinstance(func, ast.Attribute) and func.attr == "register_blueprint":
                            if register_line is None:
                                register_line = stmt.lineno
                        elif isinstance(func, ast.Name) and func.id == "_register_admin_context_processors":
                            if context_processor_line is None:
                                context_processor_line = stmt.lineno
        assert context_processor_line is not None, "未找到 _register_admin_context_processors 调用"
        assert register_line is not None, "未找到 register_blueprint 调用"
        assert context_processor_line < register_line, (
            f"context_processor(行{context_processor_line}) 必须在 register_blueprint(行{register_line}) 之前"
        )
