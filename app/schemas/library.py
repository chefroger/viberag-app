"""
VibeRAG 文档库 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CreateLibraryRequest(BaseModel):
    """创建文档库请求"""
    name: str = Field(..., min_length=1, max_length=100, description="文档库名称")
    root_path: str = Field(..., description="根目录路径")


class LibraryResponse(BaseModel):
    """文档库响应"""
    id: int
    name: str
    root_path: str
    created_at: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None
    file_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    chunk_count: int = 0

    class Config:
        from_attributes = True


class FileResponse(BaseModel):
    """文件响应"""
    id: int
    file_name: str
    file_path: str
    file_ext: Optional[str] = None
    file_size: Optional[int] = None
    doc_type: str
    doc_type_confidence: float
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    """文本块响应"""
    id: int
    content: str = Field(..., description="内容（截取前200字）")
    chunk_index: Optional[int] = None
    chunk_type: Optional[str] = None
    chunk_description: Optional[str] = None
    page_number: Optional[int] = None
    token_count: Optional[int] = None

    class Config:
        from_attributes = True


class FileDetailResponse(BaseModel):
    """文件详情响应"""
    id: int
    file_name: str
    file_path: str
    file_ext: Optional[str] = None
    file_size: Optional[int] = None
    file_mtime: Optional[float] = None
    doc_type: str
    doc_type_confidence: float
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    chunks: List[ChunkResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True
