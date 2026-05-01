"""
VibeRAG 文档库 Service

处理文档库相关业务逻辑，与 Router 层分离
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models import Library, File, Chunk
from app.services.scanner import (
    incremental_scan,
    process_scan_results,
    run_scan_task,
    get_scan_progress,
)
from app.services.vectorstore import delete_library_vectors


class LibraryService:
    """文档库 Service"""

    @staticmethod
    def create_library(db: Session, name: str, root_path: str) -> Tuple[Library, str]:
        """
        创建文档库

        Returns:
            (library, message)

        Raises:
            ValueError: 路径不存在或同名库已存在
        """
        if not Path(root_path).exists():
            raise ValueError(f"路径不存在: {root_path}")

        existing = db.query(Library).filter(Library.name == name).first()
        if existing:
            raise ValueError(f"同名库已存在: {name}")

        library = Library(
            name=name,
            root_path=root_path,
            created_at=datetime.utcnow(),
        )
        db.add(library)
        db.commit()
        db.refresh(library)

        return library, "文档库创建成功，正在后台扫描文件..."

    @staticmethod
    def list_libraries(db: Session) -> List[dict]:
        """获取文档库列表（带统计信息）"""
        libraries = db.query(Library).all()
        result = []

        for lib in libraries:
            result.append({
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
            })

        return result

    @staticmethod
    def get_library_detail(db: Session, library_id: int) -> Optional[dict]:
        """获取文档库详情"""
        library = db.query(Library).filter(Library.id == library_id).first()
        if not library:
            return None

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

    @staticmethod
    async def delete_library(db: Session, library_id: int) -> bool:
        """
        删除文档库

        Returns:
            True: 删除成功, False: 库不存在
        """
        library = db.query(Library).filter(Library.id == library_id).first()
        if not library:
            return False

        await delete_library_vectors(library_id)
        db.delete(library)
        db.commit()

        return True

    @staticmethod
    async def rescan_library(db: Session, library_id: int) -> Tuple[bool, str]:
        """
        强制重新扫描文档库

        Returns:
            (success, message)
        """
        library = db.query(Library).filter(Library.id == library_id).first()
        if not library:
            return False, "文档库不存在"

        if not Path(library.root_path).exists():
            return False, f"路径不存在: {library.root_path}"

        await delete_library_vectors(library_id)
        db.query(Chunk).filter(Chunk.library_id == library_id).delete()
        db.query(File).filter(File.library_id == library_id).delete()
        library.last_scan_at = None
        db.commit()

        return True, "强制重扫已启动，正在重建索引..."

    @staticmethod
    async def reindex_library(db: Session, library_id: int) -> Tuple[bool, str]:
        """
        重新索引文档库（删除旧向量，重新生成）

        Returns:
            (success, message)
        """
        library = db.query(Library).filter(Library.id == library_id).first()
        if not library:
            return False, "文档库不存在"

        await delete_library_vectors(library_id)
        db.query(File).filter(
            File.library_id == library_id,
            File.status == 'indexed'
        ).update({"status": "pending", "is_processed": False})

        return True, "重新索引已启动"

    @staticmethod
    def get_scan_status(db: Session, library_id: int) -> Optional[dict]:
        """获取扫描进度"""
        library = db.query(Library).filter(Library.id == library_id).first()
        if not library:
            return None

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

    @staticmethod
    def list_files(
        db: Session,
        library_id: int,
        status: Optional[str] = None,
        doc_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50
    ) -> dict:
        """获取文件列表"""
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

    @staticmethod
    def get_file_detail(db: Session, library_id: int, file_id: int) -> Optional[dict]:
        """获取文件详情"""
        file = db.query(File).filter(
            File.id == file_id,
            File.library_id == library_id
        ).first()

        if not file:
            return None

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
                    "chunk_type": c.chunk_type,
                    "chunk_description": c.chunk_description,
                    "page_number": c.page_number,
                    "token_count": c.token_count,
                }
                for c in chunks
            ]
        }

    @staticmethod
    def delete_file(db: Session, library_id: int, file_id: int) -> bool:
        """删除文件（软删除）"""
        file = db.query(File).filter(
            File.id == file_id,
            File.library_id == library_id
        ).first()

        if not file:
            return False

        file.deleted = True
        file.status = 'deleted'
        db.commit()

        return True
