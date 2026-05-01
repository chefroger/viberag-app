"""
VibeRAG SQLAlchemy 模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from app.database import Base


class Library(Base):
    """文档库"""
    __tablename__ = "library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_scan_at = Column(DateTime, nullable=True)

    files = relationship("File", back_populates="library", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="library", cascade="all, delete-orphan")


class File(Base):
    """文件"""
    __tablename__ = "file"

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(Integer, ForeignKey("library.id", ondelete="CASCADE"))
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_ext = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    file_mtime = Column(Float, nullable=True)
    content_hash = Column(String, nullable=True)
    doc_type = Column(String, default="other")
    doc_type_confidence = Column(Float, default=0.0)
    status = Column(String, default="pending")  # pending, processing, indexed, failed, deleted, unsupported_ocr_required
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    is_processed = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    library = relationship("Library", back_populates="files")
    chunks = relationship("Chunk", back_populates="file", cascade="all, delete-orphan")


class Chunk(Base):
    """文本块"""
    __tablename__ = "chunk"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("file.id", ondelete="CASCADE"))
    library_id = Column(Integer, ForeignKey("library.id", ondelete="CASCADE"))
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    chunk_type = Column(String, nullable=True)  # 表格行/章节/条款/段落
    chunk_description = Column(String, nullable=True)  # 块描述（如"报价单第1行"）
    page_number = Column(Integer, nullable=True)
    file_name = Column(String, nullable=True)
    doc_type = Column(String, default="other")
    content_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("File", back_populates="chunks")
    library = relationship("Library", back_populates="chunks")
    vectors = relationship("ChunkVector", back_populates="chunk", cascade="all, delete-orphan")


class ChunkVector(Base):
    """向量"""
    __tablename__ = "chunk_vector"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(Integer, ForeignKey("chunk.id", ondelete="CASCADE"))
    model = Column(String, default="nomic-embed-text")
    dimension = Column(Integer, default=768)
    embedding_id = Column(Integer, nullable=True)
    # 持久化存储 embedding 数据（pickle 序列化）
    embedding_data = Column(Text, nullable=True)  # JSON 序列化的向量

    chunk = relationship("Chunk", back_populates="vectors")


class Customer(Base):
    """客户"""
    __tablename__ = "customer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String, nullable=False)
    contact_name = Column(String, nullable=True)
    contact_title = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    source = Column(String, nullable=True)  # 展会/B2B平台/转介绍/主动开发
    customer_type = Column(String, nullable=True)  # 进口商/批发商/经销商/终端用户
    budget = Column(String, nullable=True)
    decision_cycle = Column(String, nullable=True)
    competitors = Column(Text, nullable=True)
    preferences = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sessions = relationship("Session", back_populates="customer")
    interactions = relationship("Interaction", back_populates="customer", cascade="all, delete-orphan")


class Prospect(Base):
    """潜在客户"""
    __tablename__ = "prospect"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    source = Column(String, nullable=True)
    stage = Column(String, default="inquiry")  # inquiry, newdev, intention
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    converted = Column(Boolean, default=False)


class Session(Base):
    """会话"""
    __tablename__ = "session"

    id = Column(String, primary_key=True)  # UUID
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    library_id = Column(Integer, ForeignKey("library.id"), nullable=True)
    session_type = Column(String, nullable=True)  # letter, script, quote, followup
    status = Column(String, default="active")  # active, ended
    input_text = Column(Text, nullable=True)
    output_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="sessions")
    turns = relationship(
        "ConversationTurn",
        primaryjoin="Session.id==foreign(ConversationTurn.session_id)",
        cascade="all, delete-orphan",
        viewonly=True
    )
    summary = relationship(
        "SessionSummary",
        primaryjoin="Session.id==foreign(SessionSummary.session_id)",
        uselist=False,
        viewonly=True
    )


class SessionSummary(Base):
    """会话摘要"""
    __tablename__ = "session_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)  # UUID，不使用 ForeignKey
    customer_id = Column(Integer, nullable=True)
    summary_text = Column(Text, nullable=False)
    key_decisions = Column(Text, nullable=True)
    pending_items = Column(Text, nullable=True)
    mentioned_products = Column(Text, nullable=True)
    mentioned_prices = Column(Text, nullable=True)
    turn_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationTurn(Base):
    """对话记录"""
    __tablename__ = "conversation_turn"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)  # UUID
    customer_id = Column(Integer, nullable=True)
    turn_index = Column(Integer, nullable=False)
    role = Column(String, nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    products_mentioned = Column(Text, nullable=True)
    prices_mentioned = Column(Text, nullable=True)
    intent = Column(String, nullable=True)
    pending_from_this_turn = Column(Text, nullable=True)


class PendingProfileUpdate(Base):
    """AI 画像更新建议（待用户确认）"""
    __tablename__ = "pending_profile_update"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"))
    session_id = Column(String, nullable=True)  # 产生建议的会话
    field_name = Column(String, nullable=False)  # 建议更新的字段名
    suggested_value = Column(Text, nullable=False)  # 建议的值
    ai_reasoning = Column(Text, nullable=True)  # AI 推理理由
    status = Column(String, default="pending")  # pending / accepted / rejected / ignored
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)  # 用户确认时间

    customer = relationship("Customer")


class Interaction(Base):
    """接触记录"""
    __tablename__ = "interaction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"))
    interaction_type = Column(String, nullable=False)  # inquiry, quotation, sample, chat, order, aftersales
    summary = Column(Text, nullable=False)
    raw_content = Column(Text, nullable=True)
    products = Column(Text, nullable=True)
    amount = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="interactions")


class CustomerLibrary(Base):
    """客户-文档库关联"""
    __tablename__ = "customer_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customer.id", ondelete="CASCADE"))
    library_id = Column(Integer, ForeignKey("library.id", ondelete="CASCADE"))
    note = Column(Text, nullable=True)


class Setting(Base):
    """设置"""
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


class IngestQueue(Base):
    """持久化摄入队列 - 支持崩溃恢复"""
    __tablename__ = "ingest_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(Integer, ForeignKey("library.id", ondelete="CASCADE"))
    file_path = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending / processing / completed / failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
