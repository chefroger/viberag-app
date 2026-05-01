"""
VibeRAG 客户 Service

处理客户相关业务逻辑，与 Router 层分离
"""
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models import Customer, Prospect, CustomerLibrary, Library, PendingProfileUpdate


class CustomerService:
    """客户 Service"""

    @staticmethod
    def list_customers(
        db: Session,
        stage: Optional[str] = None,
        library_id: Optional[int] = None
    ) -> List[dict]:
        """获取客户列表"""
        results = []

        # 正式客户
        customers = db.query(Customer).all()
        for c in customers:
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

        # Prospect
        query = db.query(Prospect)
        if stage:
            query = query.filter(Prospect.stage == stage)

        prospects = query.all()
        for p in prospects:
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

        results.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return results

    @staticmethod
    def get_customer(db: Session, customer_id: int) -> Optional[dict]:
        """获取客户详情"""
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return None

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
            "libraries": [{"id": lib.id, "name": lib.name} for lib in libraries]
        }

    @staticmethod
    def update_customer(db: Session, customer_id: int, update_data: dict) -> Optional[Customer]:
        """更新客户信息"""
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return None

        for key, value in update_data.items():
            if value is not None and hasattr(customer, key):
                setattr(customer, key, value)

        db.commit()
        return customer

    @staticmethod
    def create_customer(
        db: Session,
        data: dict,
        library_ids: Optional[List[int]] = None
    ) -> Tuple[Customer, str]:
        """创建客户（先查重再创建）"""
        existing = db.query(Customer).filter(
            Customer.company_name == data.get("company_name")
        ).first()

        if existing:
            raise ValueError("客户已存在，请使用查重功能确认是否为同一客户")

        customer = Customer(**data)
        db.add(customer)
        db.flush()

        if library_ids:
            for lib_id in library_ids:
                link = CustomerLibrary(customer_id=customer.id, library_id=lib_id)
                db.add(link)

        db.commit()
        return customer, "created"

    @staticmethod
    def check_duplicate(db: Session, company_name: str) -> dict:
        """客户查重"""
        matches = db.query(Customer).filter(
            Customer.company_name.ilike(f"%{company_name}%")
        ).all()

        if not matches:
            return {"has_duplicate": False, "matches": []}

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

        return {"has_duplicate": True, "matches": results}

    @staticmethod
    def delete_customer(db: Session, customer_id: int) -> bool:
        """删除客户"""
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return False

        db.delete(customer)
        db.commit()
        return True

    @staticmethod
    def create_prospect(db: Session, data: dict) -> Prospect:
        """创建潜在客户"""
        prospect = Prospect(**data)
        db.add(prospect)
        db.commit()
        db.refresh(prospect)
        return prospect

    @staticmethod
    def update_prospect(db: Session, prospect_id: int, update_data: dict) -> Optional[Prospect]:
        """更新潜在客户"""
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
        if not prospect:
            return None

        for key, value in update_data.items():
            if value is not None and hasattr(prospect, key):
                setattr(prospect, key, value)

        db.commit()
        return prospect

    @staticmethod
    def upgrade_prospect_stage(
        db: Session,
        prospect_id: int,
        action: str,
        customer_data: Optional[dict] = None
    ) -> Tuple[bool, dict]:
        """潜在客户阶段升级"""
        prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
        if not prospect:
            return False, {"error": "潜在客户不存在"}

        if action == "start_followup":
            if prospect.stage != "inquiry":
                return False, {"error": "只有询盘阶段才能开始跟进"}
            prospect.stage = "newdev"
            db.commit()
            return True, {"prospect_id": prospect_id, "new_stage": "newdev", "status": "upgraded"}

        elif action == "confirm_customer":
            if prospect.stage != "newdev":
                return False, {"error": "只有新开发阶段才能确认添加为客户"}

            if customer_data:
                existing = db.query(Customer).filter(
                    Customer.company_name == customer_data.get("company_name")
                ).first()
                if existing:
                    return True, {"prospect_id": prospect_id, "customer_id": existing.id, "is_existing": True, "status": "linked"}

                customer = Customer(**customer_data)
                db.add(customer)
                db.flush()
                prospect.converted = True
                prospect.stage = "intention"
                db.commit()
                return True, {"prospect_id": prospect_id, "customer_id": customer.id, "is_existing": False, "status": "created"}

            return False, {"error": "confirm_customer 需要提供 customer_data"}

        elif action == "mark_deal":
            if prospect.stage not in ("newdev", "intention"):
                return False, {"error": "只有意向客户才能标记成交"}

            customer = db.query(Customer).filter(Customer.company_name == prospect.name).first()
            if customer:
                customer.updated_at = datetime.utcnow()
                db.commit()
                return True, {"prospect_id": prospect_id, "customer_id": customer.id, "stage": "deal", "status": "marked"}

            return False, {"error": "未找到对应的客户记录，请先确认客户"}

        return False, {"error": f"不支持的操作: {action}"}

    @staticmethod
    def get_profile_suggestions(db: Session, customer_id: int) -> List[dict]:
        """获取待确认的画像建议"""
        suggestions = db.query(PendingProfileUpdate).filter(
            PendingProfileUpdate.customer_id == customer_id,
            PendingProfileUpdate.status == "pending"
        ).order_by(PendingProfileUpdate.created_at.desc()).all()

        return [
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

    @staticmethod
    def review_profile_suggestion(
        db: Session,
        customer_id: int,
        suggestion_id: int,
        action: str
    ) -> Tuple[bool, dict]:
        """审查画像建议"""
        suggestion = db.query(PendingProfileUpdate).filter(
            PendingProfileUpdate.id == suggestion_id,
            PendingProfileUpdate.customer_id == customer_id
        ).first()

        if not suggestion:
            return False, {"error": "建议不存在"}

        if action == "accept":
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if customer and hasattr(customer, suggestion.field_name):
                setattr(customer, suggestion.field_name, suggestion.suggested_value)
                customer.updated_at = datetime.utcnow()

            suggestion.status = "accepted"
            suggestion.reviewed_at = datetime.utcnow()
            db.commit()
            return True, {"suggestion_id": suggestion_id, "action": "accepted", "field_name": suggestion.field_name, "new_value": suggestion.suggested_value}

        elif action == "reject":
            suggestion.status = "rejected"
            suggestion.reviewed_at = datetime.utcnow()
            db.commit()
            return True, {"suggestion_id": suggestion_id, "action": "rejected"}

        elif action == "ignore":
            suggestion.status = "ignored"
            suggestion.reviewed_at = datetime.utcnow()
            db.commit()
            return True, {"suggestion_id": suggestion_id, "action": "ignored"}

        return False, {"error": f"不支持的操作: {action}"}
