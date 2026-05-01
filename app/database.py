"""
VibeRAG 数据库连接和初始化
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from app.config import settings

# SQLAlchemy 引擎
DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """上下文管理器方式的数据库会话"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_sqlite_vec():
    """初始化 sqlite-vec 扩展（可选，失败时降级到纯 Python 实现）"""
    try:
        conn = sqlite3.connect(str(settings.DATABASE_PATH))
        try:
            conn.execute("SELECT load_extension('vec0')")
            print("sqlite-vec 扩展加载成功")
        except Exception as e:
            print(f"[WARNING] sqlite-vec 扩展加载失败，将使用纯 Python 向量存储代替: {e}")
        finally:
            conn.close()
    except Exception as e:
        print(f"[WARNING] sqlite-vec 扩展初始化失败，将使用纯 Python 向量存储代替: {e}")


def init_db():
    """初始化数据库"""
    # 创建数据目录
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 尝试加载 sqlite-vec
    init_sqlite_vec()

    # 创建所有表
    Base.metadata.create_all(bind=engine)
    print(f"数据库初始化完成: {settings.DATABASE_PATH}")


# SQL 建表语句（用于参考和直接执行）
SCHEMA_SQL = """
-- 文档库表
CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scan_at TIMESTAMP
);

-- 文件表
CREATE TABLE IF NOT EXISTS file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER REFERENCES library(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_ext TEXT,
    file_size INTEGER,
    file_mtime REAL,
    content_hash TEXT,
    doc_type TEXT DEFAULT 'other',
    doc_type_confidence REAL DEFAULT 0.0,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    chunk_count INTEGER DEFAULT 0,
    is_processed BOOLEAN DEFAULT 0,
    deleted BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chunk 表
CREATE TABLE IF NOT EXISTS chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER REFERENCES file(id) ON DELETE CASCADE,
    library_id INTEGER REFERENCES library(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    token_count INTEGER,
    chunk_index INTEGER,
    page_number INTEGER,
    file_name TEXT,
    doc_type TEXT DEFAULT 'other',
    content_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 向量表（sqlite-vec）
CREATE TABLE IF NOT EXISTS chunk_vector (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER REFERENCES chunk(id) ON DELETE CASCADE,
    model TEXT DEFAULT 'nomic-embed-text',
    dimension INTEGER DEFAULT 768,
    embedding_id INTEGER
);

-- 客户表
CREATE TABLE IF NOT EXISTS customer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    contact_title TEXT,
    phone TEXT,
    email TEXT,
    source TEXT,
    customer_type TEXT,
    budget TEXT,
    decision_cycle TEXT,
    competitors TEXT,
    preferences TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prospect 表
CREATE TABLE IF NOT EXISTS prospect (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT,
    stage TEXT DEFAULT 'inquiry',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    converted BOOLEAN DEFAULT 0
);

-- 会话表
CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    customer_id INTEGER REFERENCES customer(id),
    library_id INTEGER REFERENCES library(id),
    session_type TEXT,
    status TEXT DEFAULT 'active',
    input_text TEXT,
    output_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
);

-- 会话摘要表
CREATE TABLE IF NOT EXISTS session_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    customer_id INTEGER REFERENCES customer(id),
    summary_text TEXT NOT NULL,
    key_decisions TEXT,
    pending_items TEXT,
    mentioned_products TEXT,
    mentioned_prices TEXT,
    turn_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 对话记录表
CREATE TABLE IF NOT EXISTS conversation_turn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    customer_id INTEGER REFERENCES customer(id),
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    products_mentioned TEXT,
    prices_mentioned TEXT,
    intent TEXT,
    pending_from_this_turn TEXT
);

-- 接触记录表
CREATE TABLE IF NOT EXISTS interaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customer(id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    raw_content TEXT,
    products TEXT,
    amount TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 客户-文档库关联表
CREATE TABLE IF NOT EXISTS customer_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customer(id) ON DELETE CASCADE,
    library_id INTEGER REFERENCES library(id) ON DELETE CASCADE,
    note TEXT
);

-- 设置表
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""
