"""
VibeRAG 客户 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    """创建客户请求"""
    company_name: str = Field(..., min_length=1, max_length=200, description="公司名称")
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    source: Optional[str] = None
    customer_type: Optional[str] = None
    budget: Optional[str] = None
    decision_cycle: Optional[str] = None
    competitors: Optional[str] = None
    preferences: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    """更新客户请求"""
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    source: Optional[str] = None
    customer_type: Optional[str] = None
    budget: Optional[str] = None
    decision_cycle: Optional[str] = None
    competitors: Optional[str] = None
    preferences: Optional[str] = None
    notes: Optional[str] = None


class LibraryRef(BaseModel):
    """文档库引用"""
    id: int
    name: str

    class Config:
        from_attributes = True


class CustomerResponse(BaseModel):
    """客户响应"""
    id: int
    company_name: str
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    source: Optional[str] = None
    customer_type: Optional[str] = None
    budget: Optional[str] = None
    decision_cycle: Optional[str] = None
    competitors: Optional[str] = None
    preferences: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    libraries: List[LibraryRef] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CustomerListItem(BaseModel):
    """客户列表项"""
    id: int
    type: str  # "customer" or "prospect"
    company_name: str
    contact_name: Optional[str] = None
    source: Optional[str] = None
    stage: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DuplicateCheckRequest(BaseModel):
    """客户查重请求"""
    company_name: str = Field(..., min_length=1, max_length=200, description="公司名称")


class DuplicateMatch(BaseModel):
    """重复匹配项"""
    id: int
    company_name: str
    source: Optional[str] = None
    libraries: List[str] = Field(default_factory=list)


class ProfileSuggestion(BaseModel):
    """画像建议"""
    id: int
    field_name: str
    suggested_value: str
    ai_reasoning: Optional[str] = None
    session_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProfileSuggestionReview(BaseModel):
    """画像建议确认/拒绝"""
    action: str = Field(..., description="动作: accept/reject/ignore")


class ProspectCreate(BaseModel):
    """创建潜在客户请求"""
    name: str = Field(..., min_length=1, max_length=200, description="客户名称")
    source: Optional[str] = None
    stage: str = Field(default="inquiry", description="阶段: inquiry/newdev/intention")
    notes: Optional[str] = None


class ProspectUpdate(BaseModel):
    """更新潜在客户请求"""
    name: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None


class StageUpgradeRequest(BaseModel):
    """阶段升级请求"""
    action: str = Field(..., description="动作: start_followup/confirm_customer/mark_deal")
