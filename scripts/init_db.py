"""初始化数据库表

部署后运行此脚本创建所有表。
使用 SQLAlchemy 的 create_all()，表存在时不会重建或修改。
如需修改表结构（增删列、改类型），请使用 Flask-Migrate / Alembic 进行迁移。
"""
from app import create_app
from app.models import db


def init_db():
    app = create_app()
    with app.app_context():
        db.create_all()
        print("所有数据库表创建成功。")


if __name__ == "__main__":
    init_db()
