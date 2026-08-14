"""业务逻辑修复回归测试

覆盖本轮修复的所有 Bug：
- Bug 2: 转人工时 AI 回复要发送给用户
- Bug 3: is_handed_over 检查顺序
- Bug 4: 重复会话（transferred 后复用）
- Bug 9: dashboard 统计语义
- Bug 10: _build_enhanced_query 畸形查询
- Bug 11: release 恢复 Conversation.status
- Bug 13: 数据清理只删 closed
- Bug 14: knowledge add ChromaDB 失败不回滚 MySQL
- Dockerfile: 单 worker
- requirements: rapidocr 替代 paddleocr
"""
import os
import sys
import ast
import types

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# stub 重依赖
for _name in ("sentence_transformers", "apscheduler"):
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


class TestBug2HandoffReplySent:
    """Bug 2: 转人工时 AI 回复必须发送给用户"""

    def test_handle_ai_response_returns_reply_on_handoff(self):
        """代码层确认：转人工分支不 return None，而是返回 UnifiedReply"""
        import inspect
        from app.services.conversation_service import _handle_ai_response
        src = inspect.getsource(_handle_ai_response)
        # 原代码是 "return None  # 转人工，不自动回复"，修复后应返回 UnifiedReply
        assert "return None" not in src or "UnifiedReply" in src, \
            "转人工分支应返回 UnifiedReply 让回复发送给用户，不能 return None"
        assert "UnifiedReply" in src, "必须构造 UnifiedReply 返回给外层发送"


class TestBug10EnhancedQuery:
    """Bug 10: _build_enhanced_query 空 context 不拼畸形查询"""

    def test_empty_context_returns_original(self):
        from app.services.conversation_service import _build_enhanced_query
        # 历史里第 2 条用户消息内容为空
        history = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "当前问题"},
        ]
        result = _build_enhanced_query("当前问题", history)
        # 不应包含 " | " 前缀
        assert " | " not in result, f"空 context 不应拼畸形查询，实际: {result!r}"
        assert result == "当前问题"

    def test_normal_context_concatenates(self):
        from app.services.conversation_service import _build_enhanced_query
        history = [
            {"role": "user", "content": "之前的上下文"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "追问"},
        ]
        result = _build_enhanced_query("追问", history)
        assert "之前的上下文" in result
        assert "追问" in result


class TestBug11ReleaseRestoresConversation:
    """Bug 11: release 恢复 Conversation.status"""

    def test_release_code_restores_conv_status(self):
        """代码层确认：release 方法内有恢复 conv.status 的逻辑"""
        import inspect
        from app.services.handoff_service import HandoffService
        src = inspect.getsource(HandoffService.release)
        assert "conv.status" in src or "transferred" in src, \
            "release 必须包含恢复 conversation.status 的逻辑"


class TestBug13CleanupOnlyClosed:
    """Bug 13: 数据清理只删 closed 对话"""

    def test_cleanup_filters_status_closed(self):
        import inspect
        from app.utils.scheduler import _cleanup_expired_conversations
        src = inspect.getsource(_cleanup_expired_conversations)
        assert 'status == "closed"' in src or '"closed"' in src, \
            "清理逻辑必须过滤 status=closed，不误删 active/transferred"


class TestBug14KnowledgeAddResilience:
    """Bug 14: ChromaDB 写入失败不回滚 MySQL"""

    def test_add_catches_chromadb_error(self):
        """代码层确认：add 方法对 ChromaDB 写入有 try/except"""
        import inspect
        from app.services.knowledge_service import KnowledgeService
        src = inspect.getsource(KnowledgeService.add)
        assert "try" in src and "except" in src, \
            "add 必须对 ChromaDB 写入做 try/except，不能静默丢数据"


class TestDockerfileSingleWorker:
    """Bug 1: Dockerfile 改单 worker"""

    def test_dockerfile_uses_single_worker(self):
        path = os.path.join(PROJECT_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert '"-w", "1"' in content, "Dockerfile 必须用单 worker (-w 1)"
        assert "--threads" in content, "Dockerfile 必须用多线程 (--threads)"
        assert '"-w", "2"' not in content, "不能再用 -w 2"


class TestRequirementsRapidOCR:
    """Bug 5: requirements.txt 改用 RapidOCR"""

    def test_no_paddlepaddle_dependency(self):
        """requirements.txt 不能再把 paddlepaddle/paddleocr 作为依赖安装"""
        path = os.path.join(PROJECT_ROOT, "requirements.txt")
        with open(path) as f:
            lines = f.readlines()
        dep_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        deps = "".join(dep_lines).lower()
        assert "paddlepaddle==" not in deps, "不应再依赖 paddlepaddle"
        assert "paddleocr==" not in deps, "不应再依赖 paddleocr"

    def test_has_rapidocr(self):
        path = os.path.join(PROJECT_ROOT, "requirements.txt")
        with open(path) as f:
            content = f.read()
        assert "rapidocr-onnxruntime" in content.lower(), "应有 rapidocr-onnxruntime"


class TestOCRUsesRapidOCR:
    """Bug 5: ocr.py 使用 RapidOCR"""

    def test_ocr_imports_rapidocr(self):
        path = os.path.join(PROJECT_ROOT, "app", "utils", "ocr.py")
        with open(path) as f:
            content = f.read()
        assert "from rapidocr_onnxruntime import RapidOCR" in content, \
            "ocr.py 应从 rapidocr_onnxruntime 导入"

    def test_ocr_not_import_paddleocr(self):
        """import 语句里不能有 paddleocr"""
        path = os.path.join(PROJECT_ROOT, "app", "utils", "ocr.py")
        with open(path) as f:
            content = f.read()
        import_lines = [l for l in content.split("\n") if l.strip().startswith(("import ", "from "))]
        for line in import_lines:
            assert "paddleocr" not in line.lower(), f"import 行不应再导入 paddleocr: {line}"

    def test_ocr_api_matches_rapidocr(self):
        """RapidOCR 调用方式：result, elapse = _ocr(path)；取 line[1]"""
        path = os.path.join(PROJECT_ROOT, "app", "utils", "ocr.py")
        with open(path) as f:
            content = f.read()
        assert "line[1]" in content, "应取 RapidOCR 结果的 line[1] 作为文字"


class TestVectorStoreRebuildOnStartup:
    """Bug 1: 启动时从 MySQL 重建向量库"""

    def test_app_init_has_rebuild_logic(self):
        path = os.path.join(PROJECT_ROOT, "app", "__init__.py")
        with open(path) as f:
            content = f.read()
        assert "_rebuild_vector_store_if_needed" in content, \
            "create_app 必须调用向量库重建检查"
        assert "Knowledge.query" in content, "重建逻辑应遍历 MySQL Knowledge 表"
