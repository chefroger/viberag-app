"""
VibeRAG Ollama Embedding 服务
"""
import httpx
from typing import List, Optional

from app.config import settings


class Embedder:
    """Ollama Embedding 客户端"""

    # nomic-embed-text 最大输入长度（约 8192 字符，留一些余量）
    MAX_EMBED_LENGTH = 7500

    def __init__(self, host: str = None, model: str = None):
        self.host = host or settings.OLLAMA_HOST
        self.model = model or settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION

    def truncate_text(self, text: str) -> str:
        """截断超长文本"""
        if len(text) > self.MAX_EMBED_LENGTH:
            # 在句子边界处截断，避免截断在单词中间
            truncated = text[:self.MAX_EMBED_LENGTH]
            last_period = truncated.rfind('。')
            last_newline = truncated.rfind('\n')
            last_space = truncated.rfind(' ')

            # 找最后一个合适的断点
            break_point = max(last_period, last_newline, last_space)
            if break_point > self.MAX_EMBED_LENGTH - 200:
                return truncated[:break_point + 1]
            return truncated
        return text

    async def embed(self, text: str) -> Optional[List[float]]:
        """
        生成单个文本的 embedding

        Args:
            text: 输入文本

        Returns:
            List[float]: 768维向量，或 None（失败时）
        """
        # 截断超长文本
        text = self.truncate_text(text)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.host}/api/embeddings",
                    json={
                        "model": self.model,
                        "prompt": text,
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("embedding")
                else:
                    print(f"Embedding 失败: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            print(f"Embedding 请求异常: {e}")
            return None

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        批量生成 embedding

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 向量列表
        """
        results = []

        for text in texts:
            embedding = await self.embed(text)
            results.append(embedding)

        return results

    async def check_connection(self) -> dict:
        """检查 Ollama 是否可用，返回详细状态"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    has_embedding = any("nomic-embed-text" in name for name in model_names)
                    return {
                        "available": True,
                        "has_embedding": has_embedding,
                        "models": model_names
                    }
                return {"available": False, "has_embedding": False, "models": []}
        except Exception as e:
            return {"available": False, "has_embedding": False, "error": str(e)}

    async def pull_model(self) -> bool:
        """拉取 embedding 模型"""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/pull",
                    json={"name": self.model}
                ) as response:
                    # 流式响应
                    async for line in response.aiter_lines():
                        if line:
                            import json
                            data = json.loads(line)
                            if data.get("error"):
                                print(f"拉取模型失败: {data['error']}")
                                return False
                            if data.get("status") == "success":
                                print(f"模型 {self.model} 拉取完成")
                                return True
            return True
        except Exception as e:
            print(f"拉取模型异常: {e}")
            return False


# 全局实例
_embedder: Optional[Embedder] = None


def get_embedder() -> Embedder:
    """获取全局 Embedder 实例"""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


async def embed_chunks(chunks: List[dict]) -> List[dict]:
    """
    为 chunks 添加 embedding

    Args:
        chunks: 分块列表，每项包含 content

    Returns:
        List[dict]: 包含 embedding 的分块列表
    """
    embedder = get_embedder()
    texts = [chunk['content'] for chunk in chunks]

    embeddings = await embedder.embed_batch(texts)

    for i, embedding in enumerate(embeddings):
        chunks[i]['embedding'] = embedding

    return chunks
