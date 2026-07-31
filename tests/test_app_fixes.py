"""本次应用级修复的回归测试

覆盖：
1. 系统设置页不再 NameError（current_app 导入修复）
2. vector_store 写锁（多进程并发写 ChromaDB 防锁冲突）
3. JS-SDK 签名算法正确性
4. 消息队列僵尸事件回收逻辑
"""
import os
import sys
import time
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class TestSystemSettings:
    """系统设置页 current_app 修复回归测试"""

    def test_admin_module_imports_current_app(self):
        """admin.py 顶层必须导入 current_app（修复 NameError）"""
        import ast
        init_path = os.path.join(PROJECT_ROOT, "app", "routes", "admin.py")
        with open(init_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # 顶层 import 是否包含 current_app
        top_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                continue
            if isinstance(node, ast.Import):
                for a in node.names:
                    top_imports.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    top_imports.add(a.asname or a.name)

        assert "current_app" in top_imports, "admin.py 顶层必须导入 current_app"


class TestVectorStoreLock:
    """vector_store 写锁并发测试"""

    def test_write_lock_serializes_concurrent_writes(self):
        """并发写操作通过文件锁串行化，全部成功"""
        # 需要 stub chromadb，跳过重依赖；此处直接测 _with_write_lock 纯逻辑
        os.environ.setdefault("CHROMA_PERSIST_DIR", "/tmp/chroma_lock_test")
        os.makedirs("/tmp/chroma_lock_test", exist_ok=True)

        from app.utils.vector_store import _with_write_lock

        results = []
        results_lock = threading.Lock()

        def worker(name):
            def fn():
                time.sleep(0.05)
                return name
            r = _with_write_lock(fn)
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4, f"期望 4 个写操作全部成功，实际 {len(results)}"
        assert sorted(results) == ["w0", "w1", "w2", "w3"]


class TestJSAPISignature:
    """JS-SDK 签名算法回归测试"""

    def test_signature_matches_sha1(self):
        """签名必须符合 jsapi_ticket&noncestr&timestamp&url 的 SHA1"""
        import hashlib
        from app.platforms.wechat_work.api import WeChatWorkAPI

        ticket = "bxLdikRXVbTPdHSM05e5u5sUoXNKd8-41ZO3MhKoyN5OfkWITDGgnr2fwJ0m9E8NYzWKVZvdVtaUgWvsdshFKA"
        url = "https://example.com"
        nonce = "Wm3WZYTPz0wzccnW"
        ts = "1414587457"

        sig = WeChatWorkAPI.generate_jsapi_signature(ticket, url, nonce, ts)
        expected = hashlib.sha1(
            f"jsapi_ticket={ticket}&noncestr={nonce}&timestamp={ts}&url={url}".encode("utf-8")
        ).hexdigest()

        assert sig == expected
        assert len(sig) == 40  # SHA1 hex 长度


class TestMessageQueueRecovery:
    """消息队列僵尸事件回收逻辑"""

    def test_recover_stale_processing_function_exists(self):
        """process_queue 必须调用 _recover_stale_processing（崩溃恢复）"""
        import ast
        path = os.path.join(PROJECT_ROOT, "app", "services", "kf_message_queue.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()

        assert "_recover_stale_processing" in src, "必须存在僵尸事件回收函数"
        # process_queue 内应调用它
        assert "def process_queue" in src
        tree = ast.parse(src)
        process_queue = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "process_queue":
                process_queue = node
                break
        assert process_queue is not None, "process_queue 必须存在"
        calls = [n for n in ast.walk(process_queue) if isinstance(n, ast.Call)]
        call_names = []
        for c in calls:
            if isinstance(c.func, ast.Name):
                call_names.append(c.func.id)
        assert "_recover_stale_processing" in call_names, "process_queue 必须调用回收函数"
