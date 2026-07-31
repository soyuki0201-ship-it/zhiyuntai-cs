"""回调接口速率限制

针对企微 / 微信客服回调入口做轻量级进程内限速，防止重放攻击和异常调用风暴。

方案：滑动窗口计数（进程内存）。适用 <50条/天的正常量级，
默认限制为 60 次/分钟，远超正常业务流量，仅拦截异常风暴。

注意：
- 进程内存计数：多 Gunicorn worker 各自独立，单 worker 超限即拦截。
  由于回调流量极低（<50条/天），单 worker 计数足够兜底。
- 不使用 Redis，与项目现有技术栈一致。
"""
import time
import logging
from collections import defaultdict, deque
from functools import wraps
from flask import request, Response

logger = logging.getLogger(__name__)

# 默认限速：每分钟最多 max_requests 次
DEFAULT_MAX_REQUESTS = 60
DEFAULT_WINDOW_SECONDS = 60

# 窗口字典最大 key 数（防御性上限，防止极端情况下内存增长）
MAX_WINDOW_KEYS = 10000

# 按 (平台, 客户端IP) 记录请求时间戳窗口
_windows: dict[tuple, deque] = defaultdict(deque)


def _get_client_ip() -> str:
    """获取客户端真实 IP

    安全说明：
    - 不信任 X-Forwarded-For：客户端可伪造任意值，导致限速被绕过 + 内存无限增长。
    - 优先使用 nginx 设置的 X-Real-IP（nginx 会覆盖该 header，客户端无法伪造）。
    - 直连（不经 nginx）时回退到 socket 地址 request.remote_addr。
    """
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return request.remote_addr or "unknown"


def rate_limit(max_requests: int = DEFAULT_MAX_REQUESTS,
               window_seconds: int = DEFAULT_WINDOW_SECONDS):
    """回调限速装饰器

    窗口内超过 max_requests 次请求时返回 429。

    Args:
        max_requests: 窗口内最大请求数
        window_seconds: 窗口时长（秒）
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            key = (request.endpoint or "", _get_client_ip())
            now = time.time()
            window = _windows[key]

            # 清理窗口外的旧记录
            while window and window[0] <= now - window_seconds:
                window.popleft()

            # 防御性上限：key 数过多时清理最旧的过期窗口，避免内存失控
            if len(_windows) > MAX_WINDOW_KEYS:
                _prune_windows(now - window_seconds * 10)

            if len(window) >= max_requests:
                logger.warning(f"回调请求超限: key={key}, count={len(window)}, limit={max_requests}")
                return Response("rate limited", status=429, mimetype="text/plain")

            window.append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator


def _prune_windows(cutoff: float):
    """清理所有记录都早于 cutoff 的窗口（防止内存无限增长）"""
    stale_keys = [k for k, w in _windows.items() if not w or w[-1] <= cutoff]
    for k in stale_keys:
        del _windows[k]
