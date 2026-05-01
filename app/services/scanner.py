"""
VibeRAG 文件扫描服务
"""
import asyncio
import hashlib
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set
from sqlalchemy.orm import Session

from app.models import File, Library, IngestQueue


# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    '.txt', '.md',
    '.pdf',
    '.docx',
    '.xlsx', '.xls',
    '.pptx',
    '.png', '.jpg', '.jpeg', '.bmp',  # v0.3 OCR
    '.html', '.htm',  # v0.3
}


def get_file_hash(file_path: str) -> Optional[str]:
    """计算文件内容的 SHA256 哈希"""
    try:
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return None


def is_hidden_file(file_path: str) -> bool:
    """检查是否为隐藏文件"""
    name = os.path.basename(file_path)
    if name.startswith('.') or name.startswith('~'):
        return True

    # Windows 隐藏属性
    try:
        attrs = os.stat(file_path).st_file_attributes
        if attrs & stat.FILE_ATTRIBUTE_HIDDEN:
            return True
    except Exception:
        pass

    return False


def get_file_extension(file_path: str) -> str:
    """获取文件扩展名（小写）"""
    return Path(file_path).suffix.lower()


def scan_directory(root_path: str, recursive: bool = True) -> List[dict]:
    """
    扫描目录，返回所有支持的文件列表

    Returns:
        List of dict: [{file_path, file_name, file_ext, file_size, file_mtime}, ...]
    """
    files = []
    root = Path(root_path)

    if not root.exists():
        return files

    try:
        if recursive:
            entries = root.rglob('*')
        else:
            entries = root.glob('*')

        for entry in entries:
            # 跳过目录
            if not entry.is_file():
                continue

            # 跳过隐藏文件
            if is_hidden_file(str(entry)):
                continue

            # 检查扩展名
            ext = get_file_extension(str(entry))
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            try:
                stat_info = entry.stat()
                files.append({
                    'file_path': str(entry),
                    'file_name': entry.name,
                    'file_ext': ext,
                    'file_size': stat_info.st_size,
                    'file_mtime': stat_info.st_mtime,
                })
            except Exception:
                continue

    except PermissionError:
        pass

    return files


def incremental_scan(db: Session, library_id: int, root_path: str) -> dict:
    """
    增量扫描：对比数据库，只处理新增/修改的文件

    Returns:
        dict: {new_files, modified_files, deleted_files, unchanged_files}
    """
    # 获取当前目录中的文件
    current_files = scan_directory(root_path)
    current_paths = {f['file_path'] for f in current_files}
    current_map = {f['file_path']: f for f in current_files}

    # 获取数据库中的文件
    db_files = db.query(File).filter(
        File.library_id == library_id,
        File.deleted == False
    ).all()
    db_paths = {f.file_path for f in db_files}
    db_map = {f.file_path: f for f in db_files}

    # 分类文件
    new_paths = current_paths - db_paths  # 新文件
    deleted_paths = db_paths - current_paths  # 已删除
    common_paths = current_paths & db_paths  # 共同存在

    # 检查修改
    modified_paths = set()
    for path in common_paths:
        current = current_map[path]
        db_file = db_map[path]

        # 检查 mtime 或 size 是否变化
        if (current['file_mtime'] != db_file.file_mtime or
            current['file_size'] != db_file.file_size):
            # 进一步检查 content_hash
            current_hash = get_file_hash(path)
            if current_hash != db_file.content_hash:
                modified_paths.add(path)

    result = {
        'new_files': [current_map[p] for p in new_paths],
        'modified_files': [current_map[p] for p in modified_paths],
        'deleted_files': list(deleted_paths),
        'unchanged_files': len(common_paths) - len(modified_paths),
        'total_current': len(current_files),
        'total_db': len(db_files),
    }

    return result


def process_scan_results(db: Session, library_id: int, scan_result: dict) -> dict:
    """
    处理扫描结果：更新数据库状态

    Returns:
        dict: 处理统计
    """
    stats = {
        'new': 0,
        'modified': 0,
        'deleted': 0,
        'unchanged': scan_result.get('unchanged_files', 0),
    }

    # 处理新文件
    for file_info in scan_result.get('new_files', []):
        content_hash = get_file_hash(file_info['file_path'])
        db_file = File(
            library_id=library_id,
            file_path=file_info['file_path'],
            file_name=file_info['file_name'],
            file_ext=file_info['file_ext'],
            file_size=file_info['file_size'],
            file_mtime=file_info['file_mtime'],
            content_hash=content_hash,
            status='pending',
        )
        db.add(db_file)
        stats['new'] += 1

    # 处理修改的文件
    for file_info in scan_result.get('modified_files', []):
        db_file = db.query(File).filter(
            File.library_id == library_id,
            File.file_path == file_info['file_path']
        ).first()

        if db_file:
            content_hash = get_file_hash(file_info['file_path'])
            db_file.file_mtime = file_info['file_mtime']
            db_file.file_size = file_info['file_size']
            db_file.content_hash = content_hash
            db_file.status = 'pending'
            db_file.is_processed = False
            stats['modified'] += 1

    # 处理删除的文件（软删除）
    for file_path in scan_result.get('deleted_files', []):
        db_file = db.query(File).filter(
            File.library_id == library_id,
            File.file_path == file_path
        ).first()

        if db_file:
            db_file.deleted = True
            db_file.status = 'deleted'
            stats['deleted'] += 1

    db.commit()
    return stats


class ScanProgress:
    """扫描进度跟踪"""
    def __init__(self):
        self.total = 0
        self.processed = 0
        self.current_file = None
        self.status = 'idle'  # idle, scanning, indexing, completed, failed
        self.error_files = []

    def set_total(self, total: int):
        self.total = total

    def increment(self):
        self.processed += 1

    def set_current_file(self, filename: str):
        self.current_file = filename

    def set_status(self, status: str):
        self.status = status

    def add_error(self, filename: str, error: str):
        self.error_files.append({'filename': filename, 'error': error})

    def to_dict(self) -> dict:
        return {
            'total': self.total,
            'processed': self.processed,
            'current_file': self.current_file,
            'status': self.status,
            'progress_percent': (self.processed / self.total * 100) if self.total > 0 else 0,
            'error_count': len(self.error_files),
            'errors': self.error_files[:10],  # 只返回前10个错误
        }


# 全局扫描进度实例
_scan_progress = ScanProgress()


def get_scan_progress() -> ScanProgress:
    """获取全局扫描进度实例"""
    return _scan_progress


# ============================================================================
# 持久化摄入队列 - 支持崩溃恢复
# ============================================================================

def queue_file(db: Session, library_id: int, file_path: str) -> IngestQueue:
    """
    将文件加入持久化队列

    Args:
        db: 数据库会话
        library_id: 文档库ID
        file_path: 文件路径

    Returns:
        IngestQueue: 队列记录
    """
    # 检查是否已在队列中
    existing = db.query(IngestQueue).filter(
        IngestQueue.library_id == library_id,
        IngestQueue.file_path == file_path,
        IngestQueue.status.in_(["pending", "processing"])
    ).first()

    if existing:
        return existing

    queue_item = IngestQueue(
        library_id=library_id,
        file_path=file_path,
        status="pending"
    )
    db.add(queue_item)
    db.commit()
    return queue_item


def mark_queue_processing(db: Session, queue_id: int):
    """标记队列项为处理中"""
    item = db.query(IngestQueue).filter(IngestQueue.id == queue_id).first()
    if item:
        item.status = "processing"
        item.updated_at = datetime.utcnow()
        db.commit()


def mark_queue_completed(db: Session, queue_id: int):
    """标记队列项为已完成"""
    item = db.query(IngestQueue).filter(IngestQueue.id == queue_id).first()
    if item:
        item.status = "completed"
        item.updated_at = datetime.utcnow()
        db.commit()


def mark_queue_failed(db: Session, queue_id: int, error: str):
    """标记队列项为失败"""
    item = db.query(IngestQueue).filter(IngestQueue.id == queue_id).first()
    if item:
        item.status = "failed"
        item.error_message = error
        item.updated_at = datetime.utcnow()
        db.commit()


def get_pending_queue_items(db: Session, library_id: int) -> List[IngestQueue]:
    """获取待处理的队列项"""
    return db.query(IngestQueue).filter(
        IngestQueue.library_id == library_id,
        IngestQueue.status.in_(["pending", "processing"])
    ).all()


def cleanup_completed_queue(db: Session, library_id: int, keep_days: int = 7):
    """清理超过指定天数的已完成队列项"""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    db.query(IngestQueue).filter(
        IngestQueue.library_id == library_id,
        IngestQueue.status == "completed",
        IngestQueue.updated_at < cutoff
    ).delete()
    db.commit()


def is_file_queued(db: Session, library_id: int, file_path: str) -> bool:
    """检查文件是否已在队列中且未完成"""
    item = db.query(IngestQueue).filter(
        IngestQueue.library_id == library_id,
        IngestQueue.file_path == file_path,
        IngestQueue.status.in_(["pending", "processing"])
    ).first()
    return item is not None


# ============================================================================
# 异步扫描任务
# ============================================================================


async def run_scan_task(library_id: int, root_path: str, db: Session = None):
    """
    异步运行扫描任务（支持持久化队列崩溃恢复）

    Args:
        library_id: 文档库ID
        root_path: 根目录路径
        db: 数据库会话（可选，不传则自动创建）
    """
    from app.database import SessionLocal
    from app.services.parser import parse_file
    from app.services.embedder import embed_chunks
    from app.services.vectorstore import add_chunk_vectors

    # 如果没有传入db，则自己创建
    should_close_db = db is None
    if db is None:
        db = SessionLocal()

    progress = get_scan_progress()
    progress.set_status('scanning')

    try:
        # 0. 崩溃恢复：将所有 "processing" 状态的队列项重置为 "pending"
        # （上一次扫描可能在中途崩溃）
        crashed_items = db.query(IngestQueue).filter(
            IngestQueue.library_id == library_id,
            IngestQueue.status == "processing"
        ).all()
        for item in crashed_items:
            item.status = "pending"
            item.updated_at = datetime.utcnow()
        if crashed_items:
            db.commit()
            print(f"[Crash Recovery] 重置 {len(crashed_items)} 个队列项为 pending 状态")

        # 1. 增量扫描
        scan_result = incremental_scan(db, library_id, root_path)
        progress.set_total(scan_result['total_current'])
        db.commit()

        # 处理扫描结果
        process_scan_results(db, library_id, scan_result)

        # 2. 获取待处理文件（排除已在队列中处理的文件）
        pending_files = db.query(File).filter(
            File.library_id == library_id,
            File.status == 'pending',
            File.deleted == False
        ).all()

        # 将待处理文件加入持久化队列
        for db_file in pending_files:
            queue_file(db, library_id, db_file.file_path)

        progress.set_status('indexing')
        progress.set_total(len(pending_files))
        progress.processed = 0

        for db_file in pending_files:
            progress.set_current_file(db_file.file_name)
            progress.increment()

            try:
                # 获取队列项
                queue_item = db.query(IngestQueue).filter(
                    IngestQueue.library_id == library_id,
                    IngestQueue.file_path == db_file.file_path,
                    IngestQueue.status == "pending"
                ).first()

                if queue_item:
                    mark_queue_processing(db, queue_item.id)

                # 更新状态
                db_file.status = 'processing'
                db.commit()

                # 解析文件
                chunks = await parse_file(db_file)

                if not chunks:
                    db_file.status = 'indexed'
                    db_file.is_processed = True
                    db.commit()
                    if queue_item:
                        mark_queue_completed(db, queue_item.id)
                    continue

                # 入库 chunks
                for chunk_data in chunks:
                    from app.models import Chunk
                    chunk = Chunk(
                        file_id=db_file.id,
                        library_id=library_id,
                        content=chunk_data['content'],
                        token_count=chunk_data.get('token_count'),
                        chunk_index=chunk_data.get('chunk_index'),
                        chunk_type=chunk_data.get('chunk_type'),
                        chunk_description=chunk_data.get('chunk_description'),
                        page_number=chunk_data.get('page_number'),
                        file_name=db_file.file_name,
                        doc_type=db_file.doc_type,
                        content_hash=chunk_data.get('content_hash'),
                    )
                    db.add(chunk)
                    db.flush()

                    chunk_data['chunk_id'] = chunk.id

                db.commit()

                # 生成向量
                await embed_chunks(chunks)

                # 存储向量
                for chunk_data in chunks:
                    if 'embedding' in chunk_data and chunk_data['embedding']:
                        vec_id = await add_chunk_vectors(chunk_data['chunk_id'], chunk_data['embedding'])
                        from app.models import ChunkVector
                        cv = ChunkVector(
                            chunk_id=chunk_data['chunk_id'],
                            embedding_id=vec_id  # sqlite-vec 模式返回 internal ID，否则为 None
                        )
                        db.add(cv)

                db.commit()

                # 更新文件状态
                db_file.chunk_count = len(chunks)
                db_file.status = 'indexed'
                db_file.is_processed = True
                db.commit()

                if queue_item:
                    mark_queue_completed(db, queue_item.id)

            except Exception as e:
                db_file.status = 'failed'
                db_file.error_message = str(e)
                db.commit()
                progress.add_error(db_file.file_name, str(e))

                if queue_item:
                    mark_queue_failed(db, queue_item.id, str(e))

        # 更新文档库最后扫描时间
        library = db.query(Library).filter(Library.id == library_id).first()
        if library:
            library.last_scan_at = datetime.utcnow()

        # 清理7天前已完成的队列项
        cleanup_completed_queue(db, library_id)

        progress.set_status('completed')

    except Exception as e:
        progress.set_status('failed')
        progress.add_error('scan', str(e))
    finally:
        # 如果是自己创建的db会话，则关闭
        if should_close_db:
            db.close()
