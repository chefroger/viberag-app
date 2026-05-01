"""
VibeRAG 会话生命周期 API

规范：§3.1 / §9 v0.2
- POST /api/session/start     — 开启会话（强制加载三层上下文）
- POST /api/session/{id}/turn — 发送消息（每轮记录到 turn 表）
- POST /api/session/{id}/end  — 结束会话（自动写回摘要+画像）
- POST /api/session/{id}/clear— 清空对话历史（仅默认对话）
"""
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Session as SessionModel, ConversationTurn, SessionSummary, Customer, Interaction
from app.services.rag import rag_query
from app.middleware.inbound_interceptor import get_viberag_context

router = APIRouter(prefix="/api/session", tags=["会话"])


class StartSessionRequest(BaseModel):
    customer_id: Optional[int] = None
    library_id: Optional[int] = None
    session_type: str = "qa"  # qa, letter, script, quote, followup


class TurnRequest(BaseModel):
    content: str
    role: str = "user"  # user, assistant


@router.post("/start")
async def start_session(request: StartSessionRequest, db: Session = Depends(get_db)):
    """开启新会话"""
    session_id = str(uuid.uuid4())

    session = SessionModel(
        id=session_id,
        customer_id=request.customer_id,
        library_id=request.library_id,
        session_type=request.session_type,
        status="active"
    )
    db.add(session)
    db.commit()

    return {
        "session_id": session_id,
        "status": "active"
    }


@router.post("/{session_id}/turn")
async def send_turn(
    session_id: str,
    request: TurnRequest,
    db: Session = Depends(get_db)
):
    """
    发送消息并记录到对话轮次表
    """
    # 验证会话存在
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    if session.status == "ended":
        raise HTTPException(400, "会话已结束，请开启新会话")

    # 获取当前轮次索引
    last_turn = db.query(ConversationTurn).filter(
        ConversationTurn.session_id == session_id
    ).order_by(ConversationTurn.turn_index.desc()).first()

    turn_index = (last_turn.turn_index + 1) if last_turn else 1

    # 记录对话轮次
    turn = ConversationTurn(
        session_id=session_id,
        customer_id=session.customer_id,
        turn_index=turn_index,
        role=request.role,
        content=request.content,
        created_at=datetime.utcnow()
    )
    db.add(turn)
    db.commit()

    return {
        "turn_id": turn.id,
        "turn_index": turn_index,
        "created_at": turn.created_at.isoformat()
    }


@router.post("/{session_id}/end")
async def end_session(session_id: str, db: Session = Depends(get_db)):
    """
    结束会话：
    1. 更新会话状态
    2. 生成会话摘要（如果轮次 >= 3）
    3. 生成 AI 画像建议（客户会话）
    4. 记录最后接触时间
    """
    from app.services.rag import generate_profile_suggestions

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    # 更新会话状态
    session.status = "ended"
    session.ended_at = datetime.utcnow()
    db.commit()

    # 获取对话轮次
    turns = db.query(ConversationTurn).filter(
        ConversationTurn.session_id == session_id
    ).order_by(ConversationTurn.turn_index).all()

    turn_count = len(turns)

    # 如果轮次 >= 3，生成摘要
    summary_text = None
    if turn_count >= 3:
        summary_text = _generate_summary(turns)

    # 写入会话摘要
    if summary_text:
        session_summary = SessionSummary(
            session_id=session_id,
            customer_id=session.customer_id,
            summary_text=summary_text,
            turn_count=turn_count
        )
        db.add(session_summary)

    # 生成 AI 画像建议（仅客户会话）
    pending_suggestions = []
    if session.customer_id and turn_count >= 3:
        try:
            pending_suggestions = await generate_profile_suggestions(
                customer_id=session.customer_id,
                session_id=session_id
            )
        except Exception as e:
            print(f"生成画像建议失败: {e}")

    # 更新客户最后接触时间
    if session.customer_id:
        customer = db.query(Customer).filter(Customer.id == session.customer_id).first()
        if customer:
            customer.updated_at = datetime.utcnow()

    db.commit()

    return {
        "session_id": session_id,
        "status": "ended",
        "turn_count": turn_count,
        "has_summary": summary_text is not None,
        "pending_suggestions": len(pending_suggestions)
    }


@router.post("/{session_id}/clear")
async def clear_session(session_id: str, db: Session = Depends(get_db)):
    """
    清空对话历史（仅默认对话/未关联客户的会话）
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    # 只允许清空未关联客户的会话
    if session.customer_id is not None:
        raise HTTPException(400, "正式客户会话不能清空对话历史")

    # 删除对话轮次
    db.query(ConversationTurn).filter(
        ConversationTurn.session_id == session_id
    ).delete()

    # 删除会话摘要
    db.query(SessionSummary).filter(
        SessionSummary.session_id == session_id
    ).delete()

    db.commit()

    return {
        "session_id": session_id,
        "status": "cleared"
    }


@router.get("/{session_id}/turns")
async def get_session_turns(session_id: str, db: Session = Depends(get_db)):
    """获取会话的所有对话轮次"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(404, "会话不存在")

    turns = db.query(ConversationTurn).filter(
        ConversationTurn.session_id == session_id
    ).order_by(ConversationTurn.turn_index).all()

    return {
        "session_id": session_id,
        "turns": [
            {
                "id": t.id,
                "turn_index": t.turn_index,
                "role": t.role,
                "content": t.content,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in turns
        ]
    }


@router.get("/{session_id}/summary")
async def get_session_summary(session_id: str, db: Session = Depends(get_db)):
    """获取会话摘要"""
    summary = db.query(SessionSummary).filter(
        SessionSummary.session_id == session_id
    ).order_by(SessionSummary.updated_at.desc()).first()

    if not summary:
        raise HTTPException(404, "暂无会话摘要")

    return {
        "session_id": session_id,
        "summary": {
            "summary_text": summary.summary_text,
            "key_decisions": summary.key_decisions,
            "pending_items": summary.pending_items,
            "mentioned_products": summary.mentioned_products,
            "mentioned_prices": summary.mentioned_prices,
            "turn_count": summary.turn_count,
            "updated_at": summary.updated_at.isoformat() if summary.updated_at else None
        }
    }


def _generate_summary(turns: List[ConversationTurn]) -> str:
    """
    根据对话轮次生成摘要

    简化版本：提取关键信息
    完整版本（v0.2+）应该调用 LLM 生成

    规范 §4 / §9 v0.2:
    - 每轮对话结束后，LLM 自动生成/更新摘要
    - 当上下文 token 超过阈值（如 4000 tokens），强制生成新摘要并清空会话历史
    - 用户点击"继续"时，把最新摘要作为起点
    """
    if not turns:
        return ""

    # 统计用户消息数量
    user_turns = [t for t in turns if t.role == "user"]
    assistant_turns = [t for t in turns if t.role == "assistant"]

    # 提取提及的产品（简化：取第一条用户消息作为需求描述）
    first_user_content = user_turns[0].content if user_turns else ""
    last_user_content = user_turns[-1].content if user_turns else ""

    summary = f"会话共 {len(turns)} 轮（用户 {len(user_turns)} 轮，助手 {len(assistant_turns)} 轮）。"

    if first_user_content:
        summary += f"\n用户首句需求：{first_user_content[:100]}"

    if last_user_content and last_user_content != first_user_content:
        summary += f"\n用户最后一句话：{last_user_content[:100]}"

    # 收集待确认事项
    pending_items = [t.pending_from_this_turn for t in turns if t.pending_from_this_turn]
    if pending_items:
        summary += f"\n待确认事项：{', '.join(set(pending_items))}"

    return summary
