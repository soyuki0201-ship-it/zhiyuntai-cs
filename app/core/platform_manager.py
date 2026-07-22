"""平台管理 - 注册/发现/路由

负责：
1. 注册所有平台实例
2. 根据平台标识查找对应平台
3. 路由回调请求到对应平台的 handler
"""
import logging
from typing import Type
from app.core.platform_interface import PlatformInterface

logger = logging.getLogger(__name__)

# 全局平台注册表（支持同一平台类型的多配置）
_platforms: dict[str, list[PlatformInterface]] = {}


def register_platform(platform: PlatformInterface):
    """注册一个平台实例

    支持同一平台类型注册多个实例（如多个企业微信配置）。
    在 app/__init__.py 和后台新增/编辑平台配置时调用。
    """
    pt = platform.get_platform_type()
    if pt not in _platforms:
        _platforms[pt] = []
    # 去重：同一类型同配置 ID 只保留一个
    for i, p in enumerate(_platforms[pt]):
        if getattr(p, '_config_id', None) == getattr(platform, '_config_id', None):
            _platforms[pt][i] = platform
            logger.info(f"平台已更新: {pt} ({platform.get_platform_name()})")
            return
    _platforms[pt].append(platform)
    logger.info(f"平台已注册: {pt} ({platform.get_platform_name()}), 共 {len(_platforms[pt])} 个实例")


def get_platform(platform_type: str) -> PlatformInterface | None:
    """根据平台标识获取第一个可用平台实例"""
    instances = _platforms.get(platform_type)
    if instances:
        return instances[0]
    return None


def get_platforms(platform_type: str) -> list[PlatformInterface]:
    """获取指定类型的所有平台实例"""
    return list(_platforms.get(platform_type, []))


def get_all_platforms() -> dict[str, list[PlatformInterface]]:
    """获取所有已注册的平台（按类型分组）"""
    return dict(_platforms)


def get_enabled_platforms() -> list[PlatformInterface]:
    """从数据库获取所有已启用的平台实例

    从 platform_configs 表中读取 enabled=True 的配置，
    然后实例化对应的平台模块。
    """
    from app.models.platform_config import PlatformConfig

    configs = PlatformConfig.query.filter_by(enabled=True).all()
    result = []
    seen = set()
    for cfg in configs:
        if cfg.platform in seen:
            continue
        seen.add(cfg.platform)
        platform = get_platform(cfg.platform)
        if platform:
            # 用数据库中的配置更新平台实例
            platform._config = cfg.get_config()
            result.append(platform)
    return result


def get_platform_class(platform_type: str) -> Type[PlatformInterface] | None:
    """根据平台标识获取平台类（用于实例化）

    新增平台时需要在此添加映射。
    """
    mapping = {
        "wechat_work": "app.platforms.wechat_work:WeChatWorkPlatform",
    }
    if platform_type not in mapping:
        return None

    import importlib
    module_path, class_name = mapping[platform_type].split(":")
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        logger.error(f"加载平台类失败: {platform_type} - {e}")
        return None
