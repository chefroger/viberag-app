"""
VibeRAG 文档库管理 API
"""
import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Library, File
from app.schemas import CreateLibraryRequest
from app.services.scanner import get_scan_progress, run_scan_task
from app.services_lifecycle.library_service import LibraryService

router = APIRouter(prefix="/api/library", tags=["文档库"])


@router.post("/create")
async def create_library(
    request: CreateLibraryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """创建文档库（自动触发首次扫描）"""
    try:
        library, message = LibraryService.create_library(
            db, request.name, request.root_path
        )
        # 自动触发首次扫描
        background_tasks.add_task(run_scan_task, library.id, library.root_path)

        return {
            "id": library.id,
            "name": library.name,
            "root_path": library.root_path,
            "created_at": library.created_at,
            "message": message,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/list")
async def list_libraries(db: Session = Depends(get_db)):
    """获取文档库列表"""
    libraries = LibraryService.list_libraries(db)
    return {"libraries": libraries}


@router.get("/{library_id}")
async def get_library(library_id: int, db: Session = Depends(get_db)):
    """获取文档库详情"""
    detail = LibraryService.get_library_detail(db, library_id)
    if not detail:
        raise HTTPException(404, "文档库不存在")
    return detail


@router.delete("/{library_id}")
async def delete_library(library_id: int, db: Session = Depends(get_db)):
    """删除文档库"""
    success = await LibraryService.delete_library(db, library_id)
    if not success:
        raise HTTPException(404, "文档库不存在")
    return {"message": "文档库已删除"}


@router.post("/{library_id}/scan")
async def scan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """触发文档库扫描（后台异步）"""
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    if not Path(library.root_path).exists():
        raise HTTPException(400, f"路径不存在: {library.root_path}")

    progress = get_scan_progress()
    if progress.status in ('scanning', 'indexing'):
        return {"message": "扫描已在进行中", "progress": progress.to_dict()}

    background_tasks.add_task(run_scan_task, library_id, library.root_path)
    return {"message": "扫描已启动", "progress": progress.to_dict()}


@router.post("/{library_id}/rescan")
async def rescan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """强制重新扫描文档库"""
    success, message = await LibraryService.rescan_library(db, library_id)
    if not success:
        raise HTTPException(404, message)

    background_tasks.add_task(run_scan_task, library_id, db.query(Library).get(library_id).root_path)
    return {"message": message}


@router.get("/{library_id}/status")
async def get_scan_status(library_id: int, db: Session = Depends(get_db)):
    """获取扫描进度"""
    status = LibraryService.get_scan_status(db, library_id)
    if not status:
        raise HTTPException(404, "文档库不存在")
    return status


@router.get("/{library_id}/files")
async def list_files(
    library_id: int,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db)
):
    """获取文件列表"""
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    return LibraryService.list_files(db, library_id, status, doc_type, page, page_size)


@router.get("/{library_id}/file/{file_id}")
async def get_file(library_id: int, file_id: int, db: Session = Depends(get_db)):
    """获取文件详情"""
    detail = LibraryService.get_file_detail(db, library_id, file_id)
    if not detail:
        raise HTTPException(404, "文件不存在")
    return detail


@router.delete("/{library_id}/file/{file_id}")
async def delete_file(library_id: int, file_id: int, db: Session = Depends(get_db)):
    """删除文件（软删除）"""
    success = LibraryService.delete_file(db, library_id, file_id)
    if not success:
        raise HTTPException(404, "文件不存在")
    return {"message": "文件已删除"}


@router.post("/{library_id}/reindex")
async def reindex_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """重新索引文档库"""
    success, message = await LibraryService.reindex_library(db, library_id)
    if not success:
        raise HTTPException(404, message)

    library = db.query(Library).filter(Library.id == library_id).first()
    background_tasks.add_task(run_scan_task, library_id, library.root_path)
    return {"message": message}


@router.get("/{library_id}/progress/stream")
async def stream_scan_progress(library_id: int, db: Session = Depends(get_db)):
    """SSE 实时推送扫描进度"""
    library = db.query(Library).filter(Library.id == library_id).first()
    if not library:
        raise HTTPException(404, "文档库不存在")

    async def event_generator():
        while True:
            progress = get_scan_progress()

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

            if progress.processed > 0 and progress.total > 0:
                elapsed_per_file = progress.processed / progress.total
                remaining_files = progress.total - progress.processed
                eta_seconds = int(remaining_files * elapsed_per_file)
            else:
                eta_seconds = None

            unsupported_files = db.query(File).filter(
                File.library_id == library_id,
                File.status == 'unsupported',
                File.deleted == False
            ).count()

            data = {
                "status": progress.status,
                "total": progress.total,
                "processed": progress.processed,
                "current_file": progress.current_file,
                "progress_percent": (progress.processed / progress.total * 100) if progress.total > 0 else 0,
                "total_files": total_files,
                "indexed_files": indexed_files,
                "failed_files": failed_files,
                "unsupported_files": unsupported_files,
                "pending_files": pending_files,
                "eta_seconds": eta_seconds,
                "errors": progress.error_files[:10],
            }

            yield f"data: {json.dumps(data)}\n\n"

            if progress.status in ('completed', 'failed', 'idle'):
                yield f"data: {json.dumps({**data, 'done': True})}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
