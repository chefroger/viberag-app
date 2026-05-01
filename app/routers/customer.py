"""
VibeRAG 客户 API

规范：§3.1 / §9 v0.2
- /api/customer/list         — 客户列表
- /api/customer/<id>         — 客户画像（GET/PATCH）
- /api/customer/check-duplicate — 客户查重
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Customer, Prospect, CustomerLibrary, Library

router = APIRouter(prefix="/api/customer", tags=["客户"])


class CustomerCreate(BaseModel):
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


class CustomerUpdate(BaseModel):
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


class DuplicateCheckRequest(BaseModel):
    company_name: str


@router.get("/list")
async def list_customers(
    stage: Optional[str] = None,  # inquiry, newdev, intention, customer
    library_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    客户列表

    Args:
        stage: 客户阶段过滤（可选）
        library_id: 文档库ID（可选，用于筛选特定库的客户）
    """
    # 获取正式客户
    customers_query = db.query(Customer)

    # 获取 Prospect（未转化的潜在客户）
    prospects_query = db.query(Prospect)

    results = []

    # 添加正式客户
    customers = customers_query.all()
    for c in customers:
        # 如果指定了 library_id，检查是否关联
        if library_id:
            link = db.query(CustomerLibrary).filter(
                CustomerLibrary.customer_id == c.id,
                CustomerLibrary.library_id == library_id
            ).first()
            if not link:
                continue

        results.append({
            "id": c.id,
            "type": "customer",
            "company_name": c.company_name,
            "contact_name": c.contact_name,
            "source": c.source,
            "stage": "customer",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None
        })

    # 添加 Prospect
    prospects = prospects_query.all()
    for p in prospects:
        if stage and p.stage != stage:
            continue

        results.append({
            "id": p.id,
            "type": "prospect",
            "company_name": p.name,
            "contact_name": None,
            "source": p.source,
            "stage": p.stage,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None
        })

    # 按更新时间倒序
    results.sort(key=lambda x: x.get("updated_at") or "", reverse=True)

    return {"customers": results}


@router.get("/{customer_id}")
async def get_customer(customer_id: int, db: Session = Depends(get_db)):
    """获取客户详情"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "客户不存在")

    # 获取关联的文档库
    links = db.query(CustomerLibrary).filter(
        CustomerLibrary.customer_id == customer_id
    ).all()
    library_ids = [link.library_id for link in links]

    libraries = db.query(Library).filter(Library.id.in_(library_ids)).all() if library_ids else []

    return {
        "id": customer.id,
        "company_name": customer.company_name,
        "contact_name": customer.contact_name,
        "contact_title": customer.contact_title,
        "phone": customer.phone,
        "email": customer.email,
        "source": customer.source,
        "customer_type": customer.customer_type,
        "budget": customer.budget,
        "decision_cycle": customer.decision_cycle,
        "competitors": customer.competitors,
        "preferences": customer.preferences,
        "notes": customer.notes,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
        "libraries": [
            {"id": lib.id, "name": lib.name}
            for lib in libraries
        ]
    }


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: int,
    update: CustomerUpdate,
    db: Session = Depends(get_db)
):
    """更新客户信息"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "客户不存在")

    # 更新非空字段
    update_dict = update.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            setattr(customer, key, value)

    db.commit()

    return {"id": customer_id, "status": "updated"}


@router.post("/check-duplicate")
async def check_duplicate(request: DuplicateCheckRequest, db: Session = Depends(get_db)):
    """
    客户查重

    在创建客户前，先模糊匹配 customer 表
    """
    # 模糊匹配
    matches = db.query(Customer).filter(
        Customer.company_name.ilike(f"%{request.company_name}%")
    ).all()

    if not matches:
        return {"has_duplicate": False, "matches": []}

    # 获取每个匹配客户关联的文档库
    results = []
    for c in matches:
        links = db.query(CustomerLibrary).filter(
            CustomerLibrary.customer_id == c.id
        ).all()
        library_ids = [link.library_id for link in links]
        libraries = db.query(Library).filter(Library.id.in_(library_ids)).all() if library_ids else []

        results.append({
            "id": c.id,
            "company_name": c.company_name,
            "source": c.source,
            "libraries": [lib.name for lib in libraries]
        })

    return {
        "has_duplicate": True,
        "matches": results
    }


@router.post("/create")
async def create_customer(
    request: CustomerCreate,
    library_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db)
):
    """
    创建客户（先查重再创建）

    Args:
        request: 客户信息
        library_ids: 关联的文档库 ID 列表
    """
    # 查重
    existing = db.query(Customer).filter(
        Customer.company_name == request.company_name
    ).first()

    if existing:
        raise HTTPException(400, "客户已存在，请使用查重功能确认是否为同一客户")

    # 创建客户
    customer = Customer(
        company_name=request.company_name,
        contact_name=request.contact_name,
        contact_title=request.contact_title,
        phone=request.phone,
        email=request.email,
        source=request.source,
        customer_type=request.customer_type,
        budget=request.budget,
        decision_cycle=request.decision_cycle,
        competitors=request.competitors,
        preferences=request.preferences,
        notes=request.notes
    )
    db.add(customer)
    db.flush()

    # 关联文档库
    if library_ids:
        for lib_id in library_ids:
            link = CustomerLibrary(
                customer_id=customer.id,
                library_id=lib_id
            )
            db.add(link)

    db.commit()

    return {
        "id": customer.id,
        "company_name": customer.company_name,
        "status": "created"
    }


@router.delete("/{customer_id}")
async def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """删除客户（软删除）"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "客户不存在")

    # 软删除：标记状态等（如果需要）
    db.delete(customer)
    db.commit()

    return {"id": customer_id, "status": "deleted"}


# ============================================================================
# Prospect（潜在客户）API
# ============================================================================

class ProspectCreate(BaseModel):
    name: str
    source: Optional[str] = None
    stage: str = "inquiry"  # inquiry, newdev, intention
    notes: Optional[str] = None


class ProspectUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None


class StageUpgradeRequest(BaseModel):
    """阶段升级请求"""
    action: str  # "start_followup" -> inquiry→newdev, "confirm_customer" -> newdev→intention, "mark_deal" -> intention→customer


@router.post("/prospect/create")
async def create_prospect(request: ProspectCreate, db: Session = Depends(get_db)):
    """创建潜在客户"""
    prospect = Prospect(
        name=request.name,
        source=request.source,
        stage=request.stage,
        notes=request.notes
    )
    db.add(prospect)
    db.commit()

    return {
        "id": prospect.id,
        "name": prospect.name,
        "stage": prospect.stage,
        "status": "created"
    }


@router.patch("/prospect/{prospect_id}")
async def update_prospect(
    prospect_id: int,
    update: ProspectUpdate,
    db: Session = Depends(get_db)
):
    """更新潜在客户"""
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(404, "潜在客户不存在")

    update_dict = update.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            setattr(prospect, key, value)

    db.commit()

    return {"id": prospect_id, "status": "updated"}


@router.post("/prospect/{prospect_id}/upgrade")
async def upgrade_prospect_stage(
    prospect_id: int,
    request: StageUpgradeRequest,
    customer_data: Optional[CustomerCreate] = None,
    db: Session = Depends(get_db)
):
    """
    潜在客户阶段升级

    规范 §2.7:
    - action=start_followup: inquiry → newdev
    - action=confirm_customer: newdev → intention → 创建 customer
    - action=mark_deal: intention → customer（直接更新 customer 表的 status）
    """
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(404, "潜在客户不存在")

    if request.action == "start_followup":
        # inquiry → newdev
        if prospect.stage != "inquiry":
            raise HTTPException(400, "只有询盘阶段才能开始跟进")
        prospect.stage = "newdev"
        db.commit()
        return {
            "prospect_id": prospect_id,
            "new_stage": "newdev",
            "status": "upgraded"
        }

    elif request.action == "confirm_customer":
        # newdev → intention → 创建 customer（触发去重）
        if prospect.stage != "newdev":
            raise HTTPException(400, "只有新开发阶段才能确认添加为客户")

        # 检查是否同名客户已存在
        if customer_data:
            existing = db.query(Customer).filter(
                Customer.company_name == customer_data.company_name
            ).first()
            if existing:
                # 关联已有客户
                return {
                    "prospect_id": prospect_id,
                    "customer_id": existing.id,
                    "is_existing": True,
                    "status": "linked"
                }

            # 创建新客户
            customer = Customer(
                company_name=customer_data.company_name,
                contact_name=customer_data.contact_name,
                contact_title=customer_data.contact_title,
                phone=customer_data.phone,
                email=customer_data.email,
                source=customer_data.source or prospect.source,
                customer_type=customer_data.customer_type,
                notes=customer_data.notes
            )
            db.add(customer)
            db.flush()

            # 标记 prospect 已转化
            prospect.converted = True
            prospect.stage = "intention"

            db.commit()
            return {
                "prospect_id": prospect_id,
                "customer_id": customer.id,
                "is_existing": False,
                "status": "created"
            }

        raise HTTPException(400, "confirm_customer 需要提供 customer_data")

    elif request.action == "mark_deal":
        # intention → 成交客户（需要先有 customer_id）
        if prospect.stage not in ("newdev", "intention"):
            raise HTTPException(400, "只有意向客户才能标记成交")

        # 查找关联的 customer
        # 对于 intention 阶段的 prospect，应该已经有对应的 customer 记录
        # 这里简化处理，查找同名客户
        customer = db.query(Customer).filter(
            Customer.company_name == prospect.name
        ).first()

        if customer:
            customer.updated_at = datetime.utcnow()
            db.commit()
            return {
                "prospect_id": prospect_id,
                "customer_id": customer.id,
                "stage": "deal",
                "status": "marked"
            }

        raise HTTPException(400, "未找到对应的客户记录，请先确认客户")

    else:
        raise HTTPException(400, f"不支持的操作: {request.action}")


# ============================================================================
# AI 画像建议 API
# ============================================================================

class ProfileSuggestionReview(BaseModel):
    """画像建议确认/拒绝"""
    action: str  # "accept" | "reject" | "ignore"


@router.get("/{customer_id}/profile-suggestions")
async def get_profile_suggestions(customer_id: int, db: Session = Depends(get_db)):
    """
    获取客户的待确认画像建议列表

    返回所有 status="pending" 的建议，按创建时间倒序
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "客户不存在")

    suggestions = db.query(PendingProfileUpdate).filter(
        PendingProfileUpdate.customer_id == customer_id,
        PendingProfileUpdate.status == "pending"
    ).order_by(PendingProfileUpdate.created_at.desc()).all()

    return {
        "customer_id": customer_id,
        "suggestions": [
            {
                "id": s.id,
                "field_name": s.field_name,
                "suggested_value": s.suggested_value,
                "ai_reasoning": s.ai_reasoning,
                "session_id": s.session_id,
                "created_at": s.created_at.isoformat() if s.created_at else None
            }
            for s in suggestions
        ]
    }


@router.post("/{customer_id}/profile-suggestions/{suggestion_id}")
async def review_profile_suggestion(
    customer_id: int,
    suggestion_id: int,
    request: ProfileSuggestionReview,
    db: Session = Depends(get_db)
):
    """
    用户确认/拒绝某条画像建议

    - accept: 将建议值写入 customer 表对应字段
    - reject: 标记为已拒绝，不再展示
    - ignore: 标记为忽略，下次会话仍可再建议
    """
    suggestion = db.query(PendingProfileUpdate).filter(
        PendingProfileUpdate.id == suggestion_id,
        PendingProfileUpdate.customer_id == customer_id
    ).first()

    if not suggestion:
        raise HTTPException(404, "建议不存在")

    if request.action == "accept":
        # 写入 customer 表对应字段
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer and hasattr(customer, suggestion.field_name):
            setattr(customer, suggestion.field_name, suggestion.suggested_value)
            customer.updated_at = datetime.utcnow()

        suggestion.status = "accepted"
        suggestion.reviewed_at = datetime.utcnow()
        db.commit()

        return {
            "suggestion_id": suggestion_id,
            "action": "accepted",
            "field_name": suggestion.field_name,
            "new_value": suggestion.suggested_value
        }

    elif request.action == "reject":
        suggestion.status = "rejected"
        suggestion.reviewed_at = datetime.utcnow()
        db.commit()

        return {
            "suggestion_id": suggestion_id,
            "action": "rejected"
        }

    elif request.action == "ignore":
        suggestion.status = "ignored"
        suggestion.reviewed_at = datetime.utcnow()
        db.commit()

        return {
            "suggestion_id": suggestion_id,
            "action": "ignored"
        }

    else:
        raise HTTPException(400, f"不支持的操作: {request.action}")
