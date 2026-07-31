"""platform_form.html 模板渲染测试

验证修复：
1. 新增模式（config=None）不渲染 testConnection JS，避免访问 config.id 报错
2. 编辑模式（config=对象）正常渲染 testConnection JS
"""
import os
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates")


def _render(config):
    from jinja2 import FileSystemLoader
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.jinja_env.loader = FileSystemLoader(TEMPLATE_DIR)

    def fake_url_for(*a, **k):
        return "/admin/platforms/3/test"

    def fake_csrf(*a, **k):
        return "csrf-token"

    class FakeRequest:
        endpoint = "admin_config.platform_add"

    with app.test_request_context():
        return app.jinja_env.get_template("admin/platform_form.html").render(
            config=config,
            available=[{"type": "wechat_work", "name": "企业微信"}],
            schema={"fields": [{"key": "corp_id", "label": "企业ID", "type": "text", "required": True}]},
            schema_error=None,
            url_for=fake_url_for,
            csrf_token=fake_csrf,
            pending_count=0,
            request=FakeRequest(),
        )


class TestPlatformForm:
    def test_new_mode_no_config_renders(self):
        """新增模式（config=None）必须正常渲染，且不包含 testConnection JS"""
        html = _render(None)
        assert html  # 渲染成功，无 UndefinedError
        assert "testConnection" not in html

    def test_edit_mode_renders_test_connection(self):
        """编辑模式（config=对象）必须包含 testConnection JS"""
        class FakeConfig:
            id = 3
            platform = "wechat_work"
            name = "企业微信-生产"
            enabled = True

            def get_config(self):
                return {"corp_id": "xxx"}

        html = _render(FakeConfig())
        assert "testConnection" in html
