"""OCR 图片文字提取工具

使用 RapidOCR（PaddleOCR 模型的 ONNX 版本）。
相比原 PaddleOCR 方案：
- 体积 16MB vs 450MB（paddlepaddle）
- 无额外系统库依赖（不需要 libiomp5/libGL 等）
- 中文识别准确度接近 PaddleOCR（实测置信度 0.99+）
- 首次加载 <1 秒（PaddleOCR 约 30 秒）

部署提醒：首次运行会自动下载 ONNX 模型（约 10MB），之后自动缓存。
"""
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Global OCR instance (lazy init, loaded once with thread safety)
_ocr = None
_ocr_lock = threading.Lock()


def init_ocr():
    """初始化 RapidOCR

    Returns:
        bool: True 表示初始化成功
    """
    global _ocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
        logger.info("RapidOCR 初始化成功")
        return True
    except ImportError:
        logger.warning(
            "rapidocr-onnxruntime 未安装，图片文字提取功能不可用。"
            "部署时执行: pip install rapidocr-onnxruntime onnxruntime"
        )
        return False
    except Exception as e:
        logger.error(f"RapidOCR 初始化失败: {e}", exc_info=True)
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
        # RapidOCR 返回 (result, elapse)
        # result: [[bbox, text, score], ...] 或 None
        result, _elapse = _ocr(image_path)
        if not result:
            return ""

        # 提取文字并拼接
        lines = []
        for line in result:
            # line 格式: [bbox(4个点的坐标), text, confidence_score]
            if line and len(line) >= 2:
                lines.append(line[1])

        text = "\n".join(lines)
        logger.info(
            f"OCR 提取完成: {len(text)} 字, 文件={os.path.basename(image_path)}"
        )
        return text

    except Exception as e:
        logger.error(f"OCR 提取失败: {e}", exc_info=True)
        return ""
