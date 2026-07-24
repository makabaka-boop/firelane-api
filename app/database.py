# -*- coding: utf-8 -*-
"""数据库连接与会话管理。使用 SQLite 持久化。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 数据库文件放在项目根目录下，便于查看与备份
SQLALCHEMY_DATABASE_URL = "sqlite:///./firelane.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：提供数据库会话并保证关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
