"""
VibeRAG 会话 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """开启会话请求"""
    customer_id: Optional[int] = None
    library_id: Optional[int] = None
    session_type: str = Field(default="qa", description="会话类型: qa/letter/script/quote/followup")


class TurnRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")
    role: str = Field(default="user", description="角色: user/assistant")


class TurnItem(BaseModel):
    """对话轮次项"""
    id: int
    turn_index: int
    role: str
    content: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SummaryDetail(BaseModel):
    """摘要详情"""
    summary_text: str
    key_decisions: Optional[str] = None
    pending_items: Optional[str] = None
    mentioned_products: Optional[str] = None
    mentioned_prices: Optional[str] = None
    turn_count: int
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
