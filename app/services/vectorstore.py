"""
VibeRAG 向量存储服务（纯 Python 实现）
"""
import json
import math
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class VectorStore:
    """纯 Python 向量存储"""

    def __init__(self):
        self._vectors = {}  # chunk_id -> embedding

    def add(self, chunk_id: int, embedding: List[float]):
        """添加向量"""
        self._vectors[chunk_id] = embedding

    def search(self, query_embedding: List[float], top_k: int = 5, threshold: float = 0.35) -> List[dict]:
        """搜索相似向量"""
        results = []

        for chunk_id, embedding in self._vectors.items():
            similarity = cosine_similarity(query_embedding, embedding)
            if similarity >= threshold:
                results.append({
                    'chunk_id': chunk_id,
                    'score': similarity
                })

        # 按相似度排序
        results.sort(key=lambda x: x['score'], reverse=True)

        return results[:top_k]

    def delete(self, chunk_id: int):
        """删除向量"""
        self._vectors.pop(chunk_id, None)

    def clear(self):
        """清空所有向量"""
        self._vectors.clear()


# 全局向量存储实例
_vector_store = VectorStore()


def init_vector_table():
    """初始化向量表"""
    print("[INFO] 向量存储初始化完成（使用纯 Python 内存实现）")


def _serialize_embedding(embedding: List[float]) -> str:
    """将向量序列化为 JSON 字符串"""
    return json.dumps(embedding)


def _deserialize_embedding(data: str) -> List[float]:
    """从 JSON 字符串反序列化向量"""
    return json.loads(data)


async def add_chunk_vectors(chunk_id: int, embedding: List[float], library_id: int = 0) -> Optional[int]:
    """
    添加向量到向量存储

    Args:
        chunk_id: chunk ID
        embedding: 768维向量
        library_id: 文档库 ID

    Returns:
        int: 向量记录 ID
    """
    try:
        # 添加到内存向量存储
        _vector_store.add(chunk_id, embedding)

        # 保存到数据库（用于持久化）
        from app.database import get_db_context
        from app.models import ChunkVector

        with get_db_context() as db:
            cv = ChunkVector(
                chunk_id=chunk_id,
                model=settings.EMBEDDING_MODEL,
                dimension=settings.EMBEDDING_DIMENSION,
                embedding_data=_serialize_embedding(embedding),
            )
            db.add(cv)
            db.commit()
            return cv.id

    except Exception as e:
        print(f"添加向量失败: {e}")
        return None


async def search_vectors(
    query_embedding: List[float],
    library_id: int = None,
    top_k: int = None,
    threshold: float = None
) -> List[dict]:
    """
    搜索相似向量

    Args:
        query_embedding: 查询向量
        library_id: 文档库 ID（可选）
        top_k: 返回数量
        threshold: 相似度阈值

    Returns:
        List[dict]: [{chunk_id, library_id, score}, ...]
    """
    if top_k is None:
        top_k = settings.TOP_K
    if threshold is None:
        threshold = settings.SIMILARITY_THRESHOLD

    # 使用内存向量存储搜索
    results = _vector_store.search(query_embedding, top_k, threshold)

    # 如果指定了 library_id，需要过滤
    if library_id is not None:
        from app.database import get_db_context
        from app.models import Chunk

        filtered_results = []
        with get_db_context() as db:
            for result in results:
                chunk = db.query(Chunk).filter(Chunk.id == result['chunk_id']).first()
                if chunk and chunk.library_id == library_id:
                    result['library_id'] = library_id
                    filtered_results.append(result)

        return filtered_results

    return results


async def delete_chunk_vectors(chunk_id: int) -> bool:
    """
    删除 chunk 的向量

    Args:
        chunk_id: chunk ID

    Returns:
        bool: 是否成功
    """
    try:
        # 从内存向量存储删除
        _vector_store.delete(chunk_id)

        # 从数据库删除
        from app.database import get_db_context
        from app.models import ChunkVector

        with get_db_context() as db:
            db.query(ChunkVector).filter(ChunkVector.chunk_id == chunk_id).delete()

        return True
    except Exception as e:
        print(f"删除向量失败: {e}")
        return False


async def delete_library_vectors(library_id: int) -> bool:
    """
    删除文档库的所有向量

    Args:
        library_id: 文档库 ID

    Returns:
        bool: 是否成功
    """
    try:
        from app.database import get_db_context
        from app.models import Chunk, ChunkVector

        # 获取该库的所有 chunk_id
        with get_db_context() as db:
            chunks = db.query(Chunk).filter(Chunk.library_id == library_id).all()
            chunk_ids = [c.id for c in chunks]

        # 从内存向量存储删除
        for chunk_id in chunk_ids:
            _vector_store.delete(chunk_id)

        # 从数据库删除
        with get_db_context() as db:
            db.query(ChunkVector).filter(ChunkVector.chunk_id.in_(chunk_ids)).delete()

        return True
    except Exception as e:
        print(f"删除库向量失败: {e}")
        return False


def rebuild_vector_index():
    """从数据库重建向量索引到内存"""
    from app.database import get_db_context
    from app.models import ChunkVector

    print("正在从数据库重建向量索引...")

    # 清空内存索引
    _vector_store.clear()

    with get_db_context() as db:
        vectors = db.query(ChunkVector).all()

        for vec in vectors:
            if vec.embedding_data:
                try:
                    embedding = _deserialize_embedding(vec.embedding_data)
                    _vector_store.add(vec.chunk_id, embedding)
                except Exception as e:
                    print(f"加载向量失败 (chunk_id={vec.chunk_id}): {e}")

    count = len(_vector_store._vectors)
    print(f"向量索引重建完成，共加载 {count} 个向量")


# 初始化
init_vector_table()

# 从数据库重建向量索引（延迟执行，避免阻塞服务器启动）
import threading
def _delayed_rebuild():
    import time
    time.sleep(1)  # 短暂延迟让服务器先启动完成
    rebuild_vector_index()

threading.Thread(target=_delayed_rebuild, daemon=True).start()
