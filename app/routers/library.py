"""
VibeRAG 文档库管理 API
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Library, File, Chunk
from app.services.scanner import (
    scan_directory,
    incremental_scan,
    process_scan_results,
    get_scan_progress,
    run_scan_task,
)
from app.services.vectorstore import delete_library_vectors

router = APIRouter(prefix="/api/library", tags=["文档库"])


class CreateLibraryRequest(BaseModel):
    name: str
    root_path: str


@router.post("/create")
async def create_library(
    request: CreateLibraryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    创建文档库（自动触发首次扫描）

    Args:
        request: 包含 name 和 root_path
    """
    # 验证路径存在
    if not Path(request.root_path).exists():
        raise HTTPException(400, f"路径不存在: {request.root_path}")

    # 检查同名库
    existing = db.query(Library).filter(Library.name == request.name).first()
    if existing:
        raise HTTPException(400, f"同名库已存在: {request.name}")

    # 创建库
    library = Library(
        name=request.name,
        root_path=request.root_path,
        created_at=datetime.utcnow(),
    )
    db.add(library)
    db.commit()
    db.refresh(library)

    # 自动触发首次扫描（后台异步，不传db让任务自己创建）
    background_tasks.add_task(run_scan_task, library.id, library.root_path)

    return {
        "id": library.id,
        "name": library.name,
        "root_path": library.root_path,
        "created_at": library.created_at,
        "message": "文档库创建成功，正在后台扫描文件...",
    }


@router.get("/list")
async def list_libraries(db: Session = Depends(get_db)):
    """获取文档库列表"""
    libraries = db.query(Library).all()

    return {
        "libraries": [
            {
                "id": lib.id,
                "name": lib.name,
                "root_path": lib.root_path,
                "created_at": lib.created_at,
                "last_scan_at": lib.last_scan_at,
                "file_count": db.query(File).filter(
                    File.library_id == lib.id,
                    File.deleted == False
                ).count(),
                "processed_count": db.query(File).filter(
                    File.library_id == lib.id,
                    File.deleted == False,
                    File.is_processed == True
                ).count(),
                "failed_count": db.query(File).filter(
                    File.library_id == lib.id,
                    File.deleted == False,
                    File.status == 'failed'
                ).count(),
                "chunk_count": db.query(Chunk).filter(
                    Chunk.library_id == lib.id
                ).count(),
            }
            for lib in libraries
        ]
    }


@router.get("/{library_id}")
async def get_library(library_id: int, db: Session = Depends(get_db)):
    """获取文档库详情"""
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    file_count = db.query(File).filter(
        File.library_id == library_id,
        File.deleted == False
    ).count()

    chunk_count = db.query(Chunk).filter(Chunk.library_id == library_id).count()

    return {
        "id": library.id,
        "name": library.name,
        "root_path": library.root_path,
        "created_at": library.created_at,
        "last_scan_at": library.last_scan_at,
        "file_count": file_count,
        "chunk_count": chunk_count,
    }


@router.delete("/{library_id}")
async def delete_library(library_id: int, db: Session = Depends(get_db)):
    """删除文档库"""
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    # 删除向量
    await delete_library_vectors(library_id)

    # 删除库（级联删除文件、chunk）
    db.delete(library)
    db.commit()

    return {"message": "文档库已删除"}


@router.post("/{library_id}/scan")
async def scan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    触发文档库扫描（后台异步）

    Args:
        library_id: 文档库 ID
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    if not Path(library.root_path).exists():
        raise HTTPException(400, f"路径不存在: {library.root_path}")

    # 检查是否已在扫描中
    progress = get_scan_progress()
    if progress.status == 'scanning' or progress.status == 'indexing':
        return {
            "message": "扫描已在进行中",
            "progress": progress.to_dict()
        }

    # 启动后台扫描（不传db让任务自己创建）
    background_tasks.add_task(run_scan_task, library_id, library.root_path)

    return {
        "message": "扫描已启动",
        "progress": progress.to_dict()
    }


@router.post("/{library_id}/rescan")
async def rescan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    强制重新扫描文档库（删除旧数据后重新扫描）

    Args:
        library_id: 文档库 ID
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    if not Path(library.root_path).exists():
        raise HTTPException(400, f"路径不存在: {library.root_path}")

    # 删除旧的 chunks 和 file 记录
    from app.models import Chunk, File

    # 删除向量
    await delete_library_vectors(library_id)

    # 删除 chunk 记录
    db.query(Chunk).filter(Chunk.library_id == library_id).delete()

    # 删除 file 记录
    db.query(File).filter(File.library_id == library_id).delete()

    # 重置最后扫描时间
    library.last_scan_at = None
    db.commit()

    # 启动后台扫描
    background_tasks.add_task(run_scan_task, library_id, library.root_path)

    return {"message": "强制重扫已启动，正在重建索引..."}


@router.get("/{library_id}/status")
async def get_scan_status(library_id: int, db: Session = Depends(get_db)):
    """
    获取扫描进度

    Args:
        library_id: 文档库 ID
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    progress = get_scan_progress()

    # 获取统计信息
    total_files = db.query(File).filter(
        File.library_id == library_id,
        File.deleted == False
    ).count()

    indexed_files = db.query(File).filter(
        File.library_id == library_id,
        File.status == 'indexed',
        File.deleted == False
    ).count()

    failed_files = db.query(File).filter(
        File.library_id == library_id,
        File.status == 'failed',
        File.deleted == False
    ).count()

    pending_files = db.query(File).filter(
        File.library_id == library_id,
        File.status == 'pending',
        File.deleted == False
    ).count()

    return {
        "status": progress.status,
        "total_files": total_files,
        "indexed_files": indexed_files,
        "failed_files": failed_files,
        "pending_files": pending_files,
        "progress_percent": (indexed_files / total_files * 100) if total_files > 0 else 0,
        "current_file": progress.current_file,
        "errors": progress.error_files[:10],
    }


@router.get("/{library_id}/files")
async def list_files(
    library_id: int,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db)
):
    """
    获取文件列表

    Args:
        library_id: 文档库 ID
        status: 状态过滤（pending, processing, indexed, failed）
        doc_type: 文档类型过滤
        page: 页码
        page_size: 每页数量
    """
    query = db.query(File).filter(
        File.library_id == library_id,
        File.deleted == False
    )

    if status:
        query = query.filter(File.status == status)
    if doc_type:
        query = query.filter(File.doc_type == doc_type)

    total = query.count()
    files = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "files": [
            {
                "id": f.id,
                "file_name": f.file_name,
                "file_path": f.file_path,
                "file_ext": f.file_ext,
                "file_size": f.file_size,
                "doc_type": f.doc_type,
                "doc_type_confidence": f.doc_type_confidence,
                "status": f.status,
                "chunk_count": f.chunk_count,
                "error_message": f.error_message,
                "updated_at": f.updated_at,
            }
            for f in files
        ]
    }


@router.get("/{library_id}/file/{file_id}")
async def get_file(library_id: int, file_id: int, db: Session = Depends(get_db)):
    """获取文件详情"""
    file = db.query(File).filter(
        File.id == file_id,
        File.library_id == library_id
    ).first()

    if not file:
        raise HTTPException(404, "文件不存在")

    # 获取关联的 chunks
    chunks = db.query(Chunk).filter(Chunk.file_id == file_id).all()

    return {
        "id": file.id,
        "file_name": file.file_name,
        "file_path": file.file_path,
        "file_ext": file.file_ext,
        "file_size": file.file_size,
        "file_mtime": file.file_mtime,
        "doc_type": file.doc_type,
        "doc_type_confidence": file.doc_type_confidence,
        "status": file.status,
        "chunk_count": file.chunk_count,
        "error_message": file.error_message,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
        "chunks": [
            {
                "id": c.id,
                "content": c.content[:200] + "..." if len(c.content) > 200 else c.content,
                "chunk_index": c.chunk_index,
                "page_number": c.page_number,
                "token_count": c.token_count,
            }
            for c in chunks
        ]
    }


@router.delete("/{library_id}/file/{file_id}")
async def delete_file(library_id: int, file_id: int, db: Session = Depends(get_db)):
    """
    删除文件（软删除）

    Args:
        library_id: 文档库 ID
        file_id: 文件 ID
    """
    file = db.query(File).filter(
        File.id == file_id,
        File.library_id == library_id
    ).first()

    if not file:
        raise HTTPException(404, "文件不存在")

    file.deleted = True
    file.status = 'deleted'
    db.commit()

    return {"message": "文件已删除"}


@router.post("/{library_id}/reindex")
async def reindex_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    重新索引文档库（删除旧向量，重新生成）

    Args:
        library_id: 文档库 ID
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    # 删除旧向量
    await delete_library_vectors(library_id)

    # 重置文件状态
    db.query(File).filter(
        File.library_id == library_id,
        File.status == 'indexed'
    ).update({"status": "pending", "is_processed": False})

    # 重新扫描（不传db让任务自己创建）
    background_tasks.add_task(run_scan_task, library_id, library.root_path)

    return {"message": "重新索引已启动"}


@router.get("/{library_id}/progress/stream")
async def stream_scan_progress(library_id: int, db: Session = Depends(get_db)):
    """
    SSE 实时推送扫描进度

    规范 v1.0 P1：
    - 进度条 + 预估剩余时间
    - 当前处理文件名实时显示
    - 支持断开重连（从当前进度继续）

    Args:
        library_id: 文档库 ID
    """
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    async def event_generator():
        """SSE 事件生成器"""
        import time

        # 记录上次已推送的处理数（用于断连重连）
        last_processed = 0

        while True:
            progress = get_scan_progress()

            # 获取当前库的统计
            total_files = db.query(File).filter(
                File.library_id == library_id,
                File.deleted == False
            ).count()

            indexed_files = db.query(File).filter(
                File.library_id == library_id,
                File.status == 'indexed',
                File.deleted == False
            ).count()

            failed_files = db.query(File).filter(
                File.library_id == library_id,
                File.status == 'failed',
                File.deleted == False
            ).count()

            pending_files = db.query(File).filter(
                File.library_id == library_id,
                File.status == 'pending',
                File.deleted == False
            ).count()

            # 计算预估剩余时间（基于当前处理速度）
            if progress.processed > 0 and progress.total > 0:
                elapsed_per_file = progress.processed / progress.total
                remaining_files = progress.total - progress.processed
                eta_seconds = int(remaining_files * elapsed_per_file)
            else:
                eta_seconds = None

            # 构建 SSE 数据
            data = {
                "status": progress.status,
                "total": progress.total,
                "processed": progress.processed,
                "current_file": progress.current_file,
                "progress_percent": (progress.processed / progress.total * 100) if progress.total > 0 else 0,
                "total_files": total_files,
                "indexed_files": indexed_files,
                "failed_files": failed_files,
                "pending_files": pending_files,
                "eta_seconds": eta_seconds,
                "errors": progress.error_files[:10],
            }

            yield f"data: {json.dumps(data)}\n\n"

            # 检查是否结束
            if progress.status in ('completed', 'failed', 'idle'):
                # 发送最终状态后结束
                yield f"data: {json.dumps({**data, 'done': True})}\n\n"
                break

            # 等待下次轮询（1秒）
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        }
    )
