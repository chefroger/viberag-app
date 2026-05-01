"""
VibeRAG 问答 Schema
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    library_id: Optional[int] = None
    customer_id: Optional[int] = None
    mode: str = Field(default="qa", description="模式: qa/letter/script/quote/followup")


class SourceItem(BaseModel):
    """来源项"""
    chunk_id: int
    file_name: str
    score: float


class LetterRequest(BaseModel):
    """开发信请求"""
    question: str = Field(..., min_length=1, max_length=500, description="客户需求描述")
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


class ScriptRequest(BaseModel):
    """话术请求"""
    question: str = Field(..., min_length=1, max_length=500, description="场景描述")
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


class QuoteRequest(BaseModel):
    """报价请求"""
    question: str = Field(..., min_length=1, max_length=500, description="产品/需求描述")
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


class FollowupRequest(BaseModel):
    """跟进请求"""
    question: str = Field(..., min_length=1, max_length=500, description="客户名称或描述")
    library_id: Optional[int] = None
    customer_id: Optional[int] = None
