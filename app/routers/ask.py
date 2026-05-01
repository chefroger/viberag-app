"""
VibeRAG 问答 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.rag import rag_query
from app.middleware.inbound_interceptor import get_viberag_context

router = APIRouter(prefix="/api/ask", tags=["问答"])


class QuestionRequest(BaseModel):
    question: str
    library_id: Optional[int] = None
    customer_id: Optional[int] = None
    mode: str = "qa"


@router.post("/question")
async def ask_question(request: QuestionRequest, http_request: Request, db: Session = Depends(get_db)):
    """RAG 问答"""
    if not request.question or not request.question.strip():
        raise HTTPException(400, "问题不能为空")

    if request.mode not in ('qa', 'letter', 'script', 'quote', 'followup'):
        raise HTTPException(400, f"不支持的模式: {request.mode}")

    # 获取拦截器注入的上下文（Layer 3 客户画像 + Layer 1 会话摘要）
    viberag_context = get_viberag_context(http_request)

    answer, sources = await rag_query(
        question=request.question,
        library_id=request.library_id,
        customer_id=request.customer_id,
        mode=request.mode,
        viberag_context=viberag_context
    )

    return {
        "answer": answer,
        "sources": sources,
        "mode": request.mode,
        "missing_fields_warning": viberag_context.get("missing_fields_warning", [])
    }


class LetterRequest(BaseModel):
    customer_info: str
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


@router.post("/letter")
async def generate_letter(request: LetterRequest, http_request: Request, db: Session = Depends(get_db)):
    """生成开发信"""
    viberag_context = get_viberag_context(http_request)

    answer, sources = await rag_query(
        question=request.customer_info,
        library_id=request.library_id,
        customer_id=request.customer_id,
        mode='letter',
        viberag_context=viberag_context
    )

    return {
        "letter": answer,
        "sources": sources,
    }


class ScriptRequest(BaseModel):
    scenario: str
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


@router.post("/script")
async def generate_script(request: ScriptRequest, http_request: Request, db: Session = Depends(get_db)):
    """生成销售话术"""
    viberag_context = get_viberag_context(http_request)

    answer, sources = await rag_query(
        question=request.scenario,
        library_id=request.library_id,
        customer_id=request.customer_id,
        mode='script',
        viberag_context=viberag_context
    )

    return {
        "script": answer,
        "sources": sources,
    }


class QuoteRequest(BaseModel):
    product_info: str
    library_id: Optional[int] = None
    customer_id: Optional[int] = None


@router.post("/quote")
async def generate_quote(request: QuoteRequest, http_request: Request, db: Session = Depends(get_db)):
    """报价建议"""
    viberag_context = get_viberag_context(http_request)

    answer, sources = await rag_query(
        question=request.product_info,
        library_id=request.library_id,
        customer_id=request.customer_id,
        mode='quote',
        viberag_context=viberag_context
    )

    return {
        "quote": answer,
        "sources": sources,
    }


class FollowupRequest(BaseModel):
    customer_name: str
    customer_id: Optional[int] = None


@router.post("/followup")
async def generate_followup(request: FollowupRequest, http_request: Request, db: Session = Depends(get_db)):
    """跟进建议"""
    viberag_context = get_viberag_context(http_request)

    answer, sources = await rag_query(
        question=request.customer_name,
        library_id=None,
        customer_id=request.customer_id,
        mode='followup',
        viberag_context=viberag_context
    )

    return {
        "followup": answer,
        "sources": sources,
    }
