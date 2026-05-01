"""
VibeRAG 入口拦截器（Inbound Interceptor）

每次 /api/ask/* 请求前强制加载三层上下文：
- Layer 3: 客户画像
- Layer 1: 最近会话摘要
- RAG 检索结果

规范：§2.8 / §3.1.1
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.database import get_db_context


class InboundInterceptorMiddleware(BaseHTTPMiddleware):
    """
    入口拦截器中间件

    触发时机：每个 /api/ask/* 请求前
    行为：
    - 默认对话：跳过客户层，直接放行
    - 客户对话：强制加载客户画像 + 会话摘要，注入 request.state.viberag_context
    """

    async def dispatch(self, request: Request, call_next):
        # 只拦截 /api/ask/* 路由
        if not request.url.path.startswith("/api/ask"):
            return await call_next(request)

        # 提取会话类型和客户身份
        # 方式1: Header
        session_type = request.headers.get("X-Session-Type")
        customer_id = request.headers.get("X-Customer-ID")

        # 方式2: Query Parameter
        if not customer_id:
            customer_id = request.query_params.get("customer_id")

        # 判断模式
        is_default_mode = (session_type == "default") or (not customer_id)

        if is_default_mode:
            # 默认对话：跳过客户层，直接放行
            request.state.viberag_context = {
                "mode": "default",
                "customer": None,
                "recent_summary": None,
                "missing_fields_warning": []
            }
        else:
            # 客户对话：加载 Layer3 客户画像 + Layer1 会话摘要
            context = await self._load_customer_context(customer_id)
            request.state.viberag_context = context

        return await call_next(request)

    async def _load_customer_context(self, customer_id: int) -> dict:
        """
        加载客户上下文

        Returns:
            dict: {
                "mode": "customer",
                "customer": customer_dict or None,
                "recent_summary": session_summary_dict or None,
                "missing_fields_warning": [str, ...]
            }
        """
        from app.models import Customer, SessionSummary

        missing = []

        with get_db_context() as db:
            # 加载客户画像 (Layer 3)
            customer = db.query(Customer).filter(Customer.id == customer_id).first()

            if not customer:
                # 客户不存在，不阻断但警告
                missing.append("客户不存在")

            # 加载最近会话摘要 (Layer 1)
            recent = db.query(SessionSummary).filter(
                SessionSummary.customer_id == customer_id
            ).order_by(SessionSummary.updated_at.desc()).first()

            # 校验关键字段（警告但不阻断）
            if customer:
                if not customer.budget and not customer.notes:
                    missing.append("客户偏好（建议完善：预算/偏好）")
            else:
                missing.append("客户画像缺失")

            if not recent:
                missing.append("历史会话摘要（新客户或久未跟进）")

        # 构建上下文
        context = {
            "mode": "customer",
            "customer": _customer_to_dict(customer) if customer else None,
            "recent_summary": _summary_to_dict(recent) if recent else None,
            "missing_fields_warning": missing
        }

        return context


def _customer_to_dict(customer) -> dict:
    """将 Customer 模型转换为字典"""
    if customer is None:
        return None
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
    }


def _summary_to_dict(summary) -> dict:
    """将 SessionSummary 模型转换为字典"""
    if summary is None:
        return None
    return {
        "id": summary.id,
        "session_id": summary.session_id,
        "customer_id": summary.customer_id,
        "summary_text": summary.summary_text,
        "key_decisions": summary.key_decisions,
        "pending_items": summary.pending_items,
        "mentioned_products": summary.mentioned_products,
        "mentioned_prices": summary.mentioned_prices,
        "turn_count": summary.turn_count,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
    }


def get_viberag_context(request: Request) -> dict:
    """
    从 request.state 获取 VibeRAG 上下文

    如果没有拦截器设置（直接调用 API 时），返回默认上下文
    """
    if hasattr(request.state, "viberag_context"):
        return request.state.viberag_context

    # 默认值：未拦截时返回默认模式
    return {
        "mode": "default",
        "customer": None,
        "recent_summary": None,
        "missing_fields_warning": []
    }
