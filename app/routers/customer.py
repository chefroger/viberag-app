"""
VibeRAG 客户 API

规范：§3.1 / §9 v0.2
- /api/customer/list         — 客户列表
- /api/customer/<id>         — 客户画像（GET/PATCH）
- /api/customer/check-duplicate — 客户查重
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    CustomerCreate,
    CustomerUpdate,
    DuplicateCheckRequest,
    ProspectCreate,
    ProspectUpdate,
    StageUpgradeRequest,
    ProfileSuggestionReview,
)
from app.services_lifecycle.customer_service import CustomerService

router = APIRouter(prefix="/api/customer", tags=["客户"])


@router.get("/list")
async def list_customers(
    stage: Optional[str] = None,
    library_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """客户列表"""
    customers = CustomerService.list_customers(db, stage, library_id)
    return {"customers": customers}


@router.get("/{customer_id}")
async def get_customer(customer_id: int, db: Session = Depends(get_db)):
    """获取客户详情"""
    customer = CustomerService.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(404, "客户不存在")
    return customer


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: int,
    update: CustomerUpdate,
    db: Session = Depends(get_db)
):
    """更新客户信息"""
    customer = CustomerService.update_customer(
        db, customer_id, update.model_dump(exclude_unset=True)
    )
    if not customer:
        raise HTTPException(404, "客户不存在")
    return {"id": customer_id, "status": "updated"}


@router.post("/check-duplicate")
async def check_duplicate(request: DuplicateCheckRequest, db: Session = Depends(get_db)):
    """客户查重"""
    return CustomerService.check_duplicate(db, request.company_name)


@router.post("/create")
async def create_customer(
    request: CustomerCreate,
    library_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db)
):
    """创建客户（先查重再创建）"""
    try:
        customer, status = CustomerService.create_customer(
            db, request.model_dump(), library_ids
        )
        return {"id": customer.id, "company_name": customer.company_name, "status": status}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{customer_id}")
async def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """删除客户"""
    success = CustomerService.delete_customer(db, customer_id)
    if not success:
        raise HTTPException(404, "客户不存在")
    return {"id": customer_id, "status": "deleted"}


# ============================================================================
# Prospect（潜在客户）API
# ============================================================================

@router.post("/prospect/create")
async def create_prospect(request: ProspectCreate, db: Session = Depends(get_db)):
    """创建潜在客户"""
    prospect = CustomerService.create_prospect(db, request.model_dump())
    return {"id": prospect.id, "name": prospect.name, "stage": prospect.stage, "status": "created"}


@router.patch("/prospect/{prospect_id}")
async def update_prospect(
    prospect_id: int,
    update: ProspectUpdate,
    db: Session = Depends(get_db)
):
    """更新潜在客户"""
    prospect = CustomerService.update_prospect(
        db, prospect_id, update.model_dump(exclude_unset=True)
    )
    if not prospect:
        raise HTTPException(404, "潜在客户不存在")
    return {"id": prospect_id, "status": "updated"}


@router.post("/prospect/{prospect_id}/upgrade")
async def upgrade_prospect_stage(
    prospect_id: int,
    request: StageUpgradeRequest,
    customer_data: Optional[CustomerCreate] = None,
    db: Session = Depends(get_db)
):
    """潜在客户阶段升级"""
    customer_dict = customer_data.model_dump() if customer_data else None
    success, result = CustomerService.upgrade_prospect_stage(
        db, prospect_id, request.action, customer_dict
    )
    if not success:
        raise HTTPException(400, result.get("error", "操作失败"))
    return result


# ============================================================================
# AI 画像建议 API
# ============================================================================

@router.get("/{customer_id}/profile-suggestions")
async def get_profile_suggestions(customer_id: int, db: Session = Depends(get_db)):
    """获取客户的待确认画像建议列表"""
    customer = CustomerService.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(404, "客户不存在")

    suggestions = CustomerService.get_profile_suggestions(db, customer_id)
    return {"customer_id": customer_id, "suggestions": suggestions}


@router.post("/{customer_id}/profile-suggestions/{suggestion_id}")
async def review_profile_suggestion(
    customer_id: int,
    suggestion_id: int,
    request: ProfileSuggestionReview,
    db: Session = Depends(get_db)
):
    """用户确认/拒绝某条画像建议"""
    success, result = CustomerService.review_profile_suggestion(
        db, customer_id, suggestion_id, request.action
    )
    if not success:
        raise HTTPException(404, result.get("error", "建议不存在"))
    return result
