"""数据库迁移脚本

处理以下变更（这些变更 db.create_all() 不会自动应用到已有表）：
1. conversations 表新增 platform_config_id 字段
2. conversations.user_id VARCHAR(64) → VARCHAR(128)
3. conversations.group_id VARCHAR(64) → VARCHAR(128)
4. handoffs.user_id VARCHAR(64) → VARCHAR(128)
5. messages 表新增 image_path 字段
6. ai_providers.api_key VARCHAR(512) → VARCHAR(1024)

安全说明：每条 ALTER 都有"字段已存在"保护，重复执行不会报错。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("开始数据库迁移...")
    migrations_run = 0

    # 1. conversations 表新增 platform_config_id
    try:
        db.session.execute(text(
            "ALTER TABLE conversations ADD COLUMN platform_config_id INT DEFAULT NULL COMMENT '平台配置ID，用于追溯具体配置实例'"
        ))
        db.session.commit()
        print("  ✅ 已添加 conversations.platform_config_id")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        if "Duplicate column" in str(e):
            print("  ⏭️ conversations.platform_config_id 已存在，跳过")
        else:
            print(f"  ❌ conversations.platform_config_id 添加失败: {e}")

    # 2. conversations.user_id VARCHAR(64) → VARCHAR(128)
    try:
        db.session.execute(text(
            "ALTER TABLE conversations MODIFY COLUMN user_id VARCHAR(128) NOT NULL COMMENT '客户ID：平台用户唯一标识'"
        ))
        db.session.commit()
        print("  ✅ 已变更 conversations.user_id → VARCHAR(128)")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        print(f"  ❌ conversations.user_id 变更失败: {e}")

    # 3. conversations.group_id VARCHAR(64) → VARCHAR(128)
    try:
        db.session.execute(text(
            "ALTER TABLE conversations MODIFY COLUMN group_id VARCHAR(128) DEFAULT NULL COMMENT '群ID（仅群聊通道有值）'"
        ))
        db.session.commit()
        print("  ✅ 已变更 conversations.group_id → VARCHAR(128)")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        print(f"  ❌ conversations.group_id 变更失败: {e}")

    # 4. handoffs.user_id VARCHAR(64) → VARCHAR(128)
    try:
        db.session.execute(text(
            "ALTER TABLE handoffs MODIFY COLUMN user_id VARCHAR(128) NOT NULL COMMENT '被接管的客户ID'"
        ))
        db.session.commit()
        print("  ✅ 已变更 handoffs.user_id → VARCHAR(128)")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        print(f"  ❌ handoffs.user_id 变更失败: {e}")

    # 5. messages 表新增 image_path
    try:
        db.session.execute(text(
            "ALTER TABLE messages ADD COLUMN image_path VARCHAR(256) DEFAULT NULL COMMENT '图片消息：本地缓存的图片路径'"
        ))
        db.session.commit()
        print("  ✅ 已添加 messages.image_path")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        if "Duplicate column" in str(e):
            print("  ⏭️ messages.image_path 已存在，跳过")
        else:
            print(f"  ❌ messages.image_path 添加失败: {e}")

    # 6. ai_providers.api_key VARCHAR(512) → VARCHAR(1024)
    try:
        db.session.execute(text(
            "ALTER TABLE ai_providers MODIFY COLUMN api_key VARCHAR(1024) NOT NULL COMMENT 'API Key（AES 加密存储）'"
        ))
        db.session.commit()
        print("  ✅ 已变更 ai_providers.api_key → VARCHAR(1024)")
        migrations_run += 1
    except Exception as e:
        db.session.rollback()
        print(f"  ❌ ai_providers.api_key 变更失败: {e}")

    # 7. 确保所有新表存在
    db.create_all()
    print("  ✅ db.create_all() 完成（新表已创建）")

    if migrations_run > 0:
        print(f"\n🎉 迁移完成！共执行 {migrations_run} 项变更")
    else:
        print("\n✅ 数据库已是最新，无需迁移")
