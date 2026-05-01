"""
VibeRAG Pydantic Schemas

通用请求/响应模型
"""
from typing import Optional, List, Any, Generic, TypeVar
from pydantic import BaseModel, Field


T = TypeVar("T")


class BaseResponse(BaseModel, Generic[T]):
    """通用响应包装"""
    code: int = Field(default=0, description="状态码，0为成功")
    message: str = Field(default="success", description="消息")
    data: Optional[T] = Field(default=None, description="数据")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    total: int = Field(..., description="总数")
    page: int = Field(default=1, description="当前页")
    page_size: int = Field(default=50, description="每页数量")
    items: List[T] = Field(default_factory=list, description="数据列表")


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    detail: Optional[str] = Field(default=None, description="详细错误信息")
    recoverable: bool = Field(default=True, description="是否可恢复")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="状态 ok/error")
    version: str = Field(..., description="版本号")


class ScanProgressResponse(BaseModel):
    """扫描进度响应"""
    status: str = Field(..., description="状态: idle/scanning/indexing/completed/failed")
    total: int = Field(default=0, description="总数")
    processed: int = Field(default=0, description="已处理")
    current_file: Optional[str] = Field(default=None, description="当前处理文件")
    progress_percent: float = Field(default=0.0, description="进度百分比")
    total_files: int = Field(default=0, description="文件总数")
    indexed_files: int = Field(default=0, description="已索引文件数")
    failed_files: int = Field(default=0, description="失败文件数")
    pending_files: int = Field(default=0, description="待处理文件数")
    eta_seconds: Optional[int] = Field(default=None, description="预估剩余秒数")
    errors: List[dict] = Field(default_factory=list, description="错误列表")
