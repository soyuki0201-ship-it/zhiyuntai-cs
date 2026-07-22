"""OCR 图片文字提取工具

技术选型文档 9.3：使用 PaddleOCR 本地提取图片文字
PaddleOCR 免费、中文识别准、本地 CPU 运行

部署提醒：PaddleOCR 模型首次加载约需 30秒，之后约 0.5-2秒/张。
首次加载会自动下载模型文件（约 100MB），后续自动缓存。
"""
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Global OCR instance (lazy init, loaded once with thread safety)
_ocr = None
_ocr_lock = threading.Lock()


def init_ocr():
    """初始化 PaddleOCR（首次调用时自动下载模型）

    技术选型文档 9.3：PaddleOCR 中文识别效果业界领先
    """
    global _ocr
    try:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=False, show_log=False)
        logger.info("PaddleOCR 初始化成功")
        return True
    except ImportError:
        logger.warning("PaddleOCR 未安装，图片文字提取功能不可用。"
                        "部署时执行: pip install paddlepaddle paddleocr")
        return False
    except Exception as e:
        logger.error(f"PaddleOCR 初始化失败: {e}")
        return False


def extract_text_from_image(image_path: str) -> str:
    """从图片中提取文字

    Args:
        image_path: 图片文件路径

    Returns:
        str: 提取到的文字内容，多行用换行分隔
    """
    global _ocr

    if not os.path.exists(image_path):
        logger.error(f"图片文件不存在: {image_path}")
        return ""

    # 线程安全的懒加载 OCR
    if _ocr is None:
        with _ocr_lock:
            if _ocr is None:
                success = init_ocr()
                if not success:
                    return ""

    try:
        result = _ocr.ocr(image_path, cls=True)
        if not result or not result[0]:
            return ""

        # 提取文字并拼接
        lines = []
        for line_group in result:
            for line in line_group:
                if line and len(line) >= 2:
                    lines.append(line[1][0])

        text = "\n".join(lines)
        logger.info(f"OCR 提取完成: {len(text)} 字, 文件={os.path.basename(image_path)}")
        return text

    except Exception as e:
        logger.error(f"OCR 提取失败: {e}")
        return ""
