"""
VibeRAG 设置 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models import Setting
from app.services.embedder import get_embedder

router = APIRouter(prefix="/api/settings", tags=["设置"])


class SettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None


@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    """获取所有设置"""
    settings_list = db.query(Setting).all()
    settings_dict = {s.key: s.value for s in settings_list}

    return {
        "llm_provider": settings_dict.get("llm_provider", settings.LLM_PROVIDER),
        "api_base_url": settings_dict.get("api_base_url", settings.LLM_API_BASE_URL or ""),
        "api_key": settings_dict.get("api_key", ""),
        "model": settings_dict.get("model", settings.LLM_MODEL),
        "top_k": int(settings_dict.get("top_k", settings.TOP_K)),
        "similarity_threshold": float(settings_dict.get("similarity_threshold", settings.SIMILARITY_THRESHOLD)),
        "ollama_host": settings.OLLAMA_HOST,
        "embedding_model": settings.EMBEDDING_MODEL,
    }


@router.post("/")
async def save_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    """保存设置"""
    updates = []

    # 只更新明确提供的字段（避免 undefined/null 覆盖已有值）
    if data.llm_provider is not None and data.llm_provider != "":
        _save_setting(db, "llm_provider", data.llm_provider)
        settings.LLM_PROVIDER = data.llm_provider
        updates.append("llm_provider")

    if data.api_base_url is not None:
        _save_setting(db, "api_base_url", data.api_base_url)
        settings.LLM_API_BASE_URL = data.api_base_url if data.api_base_url else None
        updates.append("api_base_url")

    # api_key 只在明确提供新值时更新（避免 null 覆盖已有值）
    if data.api_key is not None:
        if data.api_key != "":
            _save_setting(db, "api_key", data.api_key)
            settings.LLM_API_KEY = data.api_key
            updates.append("api_key")
        # 空字符串表示要清空 API Key
        elif data.api_key == "":
            _save_setting(db, "api_key", "")
            settings.LLM_API_KEY = ""
            updates.append("api_key")

    if data.model is not None and data.model != "":
        _save_setting(db, "model", data.model)
        settings.LLM_MODEL = data.model
        updates.append("model")

    if data.top_k is not None:
        _save_setting(db, "top_k", str(data.top_k))
        settings.TOP_K = data.top_k
        updates.append("top_k")

    if data.similarity_threshold is not None:
        _save_setting(db, "similarity_threshold", str(data.similarity_threshold))
        settings.SIMILARITY_THRESHOLD = data.similarity_threshold
        updates.append("similarity_threshold")

    msg = f"已保存: {', '.join(updates)}" if updates else "没有更新任何设置"
    return {"message": msg}


def _save_setting(db: Session, key: str, value: str):
    """保存单个设置"""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
        db.add(setting)
    db.commit()


@router.post("/test-llm")
async def test_llm_connection():
    """测试 LLM 连接"""
    from app.services.rag import call_llm

    test_prompt = "请回复 'ok' 如果你能看到这条消息。"

    try:
        result = await call_llm(test_prompt)
        if "ok" in result.lower():
            return {"status": "ok", "message": "LLM 连接成功"}
        else:
            return {"status": "error", "error": f"意外响应: {result}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/ollama/pull-model")
async def pull_ollama_model(model: str = "nomic-embed-text"):
    """触发 Ollama 模型下载"""
    embedder = get_embedder()

    try:
        success = await embedder.pull_model()
        if success:
            return {"status": "started", "message": f"模型 {model} 下载已开始"}
        else:
            return {"status": "error", "error": "下载失败"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/ollama/status")
async def get_ollama_status():
    """获取 Ollama 状态"""
    embedder = get_embedder()
    status = await embedder.check_connection()

    if status.get("available"):
        if status.get("has_embedding"):
            return {
                "available": True,
                "status": "ok",
                "message": "Ollama 运行中，Embedding 模型已安装",
                "models": status.get("models", [])
            }
        else:
            return {
                "available": True,
                "status": "warning",
                "message": "Ollama 运行中，但需要下载 nomic-embed-text 模型",
                "models": status.get("models", [])
            }
    else:
        error_msg = status.get("error", "未知错误")
        return {
            "available": False,
            "status": "error",
            "message": f"Ollama 未运行: {error_msg}"
        }
