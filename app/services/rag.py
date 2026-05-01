"""
VibeRAG RAG 问答服务
"""
from typing import List, Optional, Tuple
import httpx

from app.config import settings
from app.models import Chunk, Setting
from app.services.embedder import get_embedder
from app.services.vectorstore import search_vectors
from app.database import get_db_context


def get_db_settings() -> dict:
    """从数据库读取设置，忽略缓存确保获取最新值"""
    with get_db_context() as db:
        settings_list = db.query(Setting).all()
        return {s.key: s.value for s in settings_list}


class RAGService:
    """RAG 问答服务"""

    def __init__(self):
        self.top_k = settings.TOP_K
        self.threshold = settings.SIMILARITY_THRESHOLD
        self.max_context_tokens = 4000

    async def retrieve(self, query: str, library_id: int = None) -> List[dict]:
        """
        检索相关文档片段

        Args:
            query: 查询文本
            library_id: 文档库 ID（可选）

        Returns:
            List[dict]: [{chunk, score}, ...]
        """
        # 生成查询向量
        embedder = get_embedder()
        query_embedding = await embedder.embed(query)

        if not query_embedding:
            return []

        # 搜索向量
        results = await search_vectors(
            query_embedding=query_embedding,
            library_id=library_id,
            top_k=self.top_k,
            threshold=self.threshold
        )

        if not results:
            return []

        # 获取 chunk 内容
        chunks_data = []
        with get_db_context() as db:
            for result in results:
                chunk = db.query(Chunk).filter(Chunk.id == result['chunk_id']).first()
                if chunk:
                    chunks_data.append({
                        'chunk': {
                            'id': chunk.id,
                            'content': chunk.content,
                            'file_name': chunk.file_name,
                            'doc_type': chunk.doc_type,
                            'token_count': chunk.token_count,
                        },
                        'score': result['score']
                    })

        return chunks_data

    def build_prompt(self, query: str, context_chunks: List[dict], mode: str = 'qa', viberag_context: dict = None) -> str:
        """
        构建 prompt

        Args:
            query: 用户问题
            context_chunks: 检索到的上下文
            mode: 模式（qa/letter/script/quote/followup）
            viberag_context: VibeRAG 上下文（来自入口拦截器）

        Returns:
            str: 构建好的 prompt
        """
        # 构建上下文文本
        context_text = "\n\n".join([
            f"[来源: {c['chunk']['file_name']}]\n{c['chunk']['content']}"
            for c in context_chunks
        ])

        # System prompt
        system_prompt = """你是一名资深外贸 B2B 销售专家，拥有多年出口经验，精通以下能力：
- 根据客户需求推荐合适的产品型号和配置
- 撰写专业、个性化、有说服力的英文开发信和跟进邮件
- 提供电话/视频销售话术，处理客户异议，促成成交
- 基于历史报价和成交记录给出合理报价建议
- 理解产品技术规格，能与客户工程师直接沟通
- 注意不同国家/地区的商务礼仪和沟通习惯

重要规则：
1. 回答必须基于提供的上下文内容，不要编造信息
2. 如果上下文中没有相关信息，直接告知用户"未在文档中找到相关信息"
3. 回答要简洁专业，优先使用表格展示产品信息
4. 不要在回答中标注信息来源（文件名），信息来源会在回答后单独显示
5. 用中文回答，语气专业友善
"""

        # 注入客户上下文（来自入口拦截器）
        if viberag_context and viberag_context.get("mode") == "customer":
            customer = viberag_context.get("customer")
            recent_summary = viberag_context.get("recent_summary")

            if customer:
                # Layer 3: 客户画像注入
                customer_context = f"""
【客户信息】
公司名称: {customer.get('company_name', '未知')}
客户类型: {customer.get('customer_type', '未知')}
来源渠道: {customer.get('source', '未知')}
"""
                system_prompt += customer_context

            if recent_summary:
                # Layer 1: 会话摘要注入
                summary_context = f"""
【历史会话摘要】
{recent_summary.get('summary_text', '暂无摘要')}
已确认事项: {recent_summary.get('key_decisions', '暂无')}
待确认事项: {recent_summary.get('pending_items', '暂无')}
提及产品: {recent_summary.get('mentioned_products', '暂无')}
提及价格: {recent_summary.get('mentioned_prices', '暂无')}
"""
                system_prompt += summary_context

        # 根据模式调整 user prompt
        if mode == 'qa':
            user_prompt = f"""基于以下文档内容回答问题。如果文档中没有相关信息，请明确告知。

---
{context_text}
---

问题：{query}

请简洁回答，优先用表格展示："""
        elif mode == 'letter':
            user_prompt = f"""基于以下客户文档和产品信息，生成一封开发信。

---
{context_text}
---

客户需求：{query}

请生成一封专业的英文开发信："""
        elif mode == 'script':
            user_prompt = f"""基于以下产品文档和客户信息，生成销售话术。

---
{context_text}
---

客户情况：{query}

请生成电话/视频销售话术（开场白、产品介绍、异议处理、促成）："""
        elif mode == 'quote':
            user_prompt = f"""基于以下历史报价信息，给出报价建议。

---
{context_text}
---

客户需求：{query}

请给出参考报价区间和调整建议："""
        elif mode == 'followup':
            user_prompt = f"""基于以下客户历史记录，生成跟进建议。

---
{context_text}
---

客户名称：{query}

请给出跟进话题和注意事项："""
        else:
            user_prompt = f"""基于以下文档内容回答问题。

---
{context_text}
---

问题：{query}

请回答："""

        return f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>"

    def build_default_prompt(self, query: str, mode: str = 'qa') -> str:
        """
        构建默认对话 prompt（无 RAG 上下文）

        Args:
            query: 用户问题
            mode: 模式

        Returns:
            str: 构建好的 prompt
        """
        # System prompt
        system_prompt = """你是一名资深外贸 B2B 销售专家，拥有多年出口经验，精通以下能力：
- 根据客户需求推荐合适的产品型号和配置
- 撰写专业、个性化、有说服力的英文开发信和跟进邮件
- 提供电话/视频销售话术，处理客户异议，促成成交
- 基于历史报价和成交记录给出合理报价建议
- 理解产品技术规格，能与客户工程师直接沟通
- 注意不同国家/地区的商务礼仪和沟通习惯

重要规则：
1. 用中文回答，语气专业友善
2. 如果不确定某些信息，可以说明但不要编造
"""

        # 根据模式调整 user prompt
        if mode == 'qa':
            user_prompt = f"""问题：{query}

请回答："""
        elif mode == 'letter':
            user_prompt = f"""请生成一封专业的英文开发信。

客户需求：{query}

请生成："""
        elif mode == 'script':
            user_prompt = f"""请生成销售话术。

场景：{query}

请生成话术："""
        elif mode == 'quote':
            user_prompt = f"""请给出报价建议。

产品/需求：{query}

请给出建议："""
        elif mode == 'followup':
            user_prompt = f"""请给出跟进建议。

客户情况：{query}

请给出建议："""
        else:
            user_prompt = f"问题：{query}\n\n请回答："

        return f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>"


rag_service = RAGService()


async def rag_query(
    question: str,
    library_id: int = None,
    customer_id: int = None,
    mode: str = 'qa',
    viberag_context: dict = None
) -> Tuple[str, List[dict]]:
    """
    RAG 问答

    Args:
        question: 用户问题
        library_id: 文档库 ID（可选，为 None 时走默认对话模式）
        customer_id: 客户 ID
        mode: 模式
        viberag_context: VibeRAG 上下文（来自入口拦截器，包含客户画像+会话摘要）

    Returns:
        (answer, sources)
    """
    # 没有指定文档库时，走默认对话模式（直接调用 LLM）
    if library_id is None:
        prompt = rag_service.build_default_prompt(question, mode)
        answer = await call_llm(prompt)
        return answer, []

    # 有文档库时，走 RAG 检索模式
    chunks = await rag_service.retrieve(question, library_id)

    if not chunks:
        return "未在当前文档库中找到足够相关的信息。", []

    # 构建 prompt（注入客户上下文）
    prompt = rag_service.build_prompt(question, chunks, mode, viberag_context=viberag_context)

    # 调用 LLM
    answer = await call_llm(prompt)

    # 提取来源
    sources = [
        {
            'chunk_id': c['chunk']['id'],
            'file_name': c['chunk']['file_name'],
            'score': c['score']
        }
        for c in chunks
    ]

    return answer, sources


async def call_llm(prompt: str) -> str:
    """
    调用 LLM API

    Args:
        prompt: 构建好的 prompt

    Returns:
        str: LLM 回答
    """
    db_settings = get_db_settings()
    api_key = db_settings.get('api_key') or settings.LLM_API_KEY
    model = db_settings.get('model') or settings.LLM_MODEL
    provider = db_settings.get('llm_provider') or settings.LLM_PROVIDER
    api_base = db_settings.get('api_base_url') or settings.LLM_API_BASE_URL

    if not api_key:
        return "LLM API Key 未配置，请在设置中配置"

    if not model:
        return "LLM 模型未配置，请在设置中配置"

    if provider == 'anthropic':
        return await call_anthropic(prompt, api_key, api_base)
    else:
        # OpenAI 兼容格式（OpenAI、硅基流动、自定义等）
        return await call_openai_compatible(prompt, api_key, model, api_base)


async def call_openai_compatible(prompt: str, api_key: str, model: str, api_base: str = None) -> str:
    """调用 OpenAI 兼容格式 API"""
    api_base = api_base or "https://api.openai.com/v1"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content']
            else:
                error = response.json()
                return f"API 错误: {error.get('error', {}).get('message', '未知错误')}"

    except Exception as e:
        return f"API 请求失败: {str(e)}"


async def call_anthropic(prompt: str, api_key: str, api_base: str = None, model: str = None) -> str:
    """调用 Anthropic Claude API"""
    api_base = api_base or "https://api.anthropic.com"
    model = model or "claude-3-5-sonnet-20241022"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{api_base.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data['content'][0]['text']
            else:
                error = response.json()
                return f"Claude API 错误: {error.get('error', {}).get('message', '未知错误')}"

    except Exception as e:
        return f"Claude API 请求失败: {str(e)}"


# ============================================================================
# AI 画像建议生成
# ============================================================================

async def generate_profile_suggestions(customer_id: int, session_id: str = None) -> List[dict]:
    """
    分析客户对话历史，生成画像更新建议

    规范 §6.4 AI 画像建议实现流程：
    1. 会话结束后，AI 分析 conversation_turn 历史记录
    2. 提取候选画像字段（偏好产品/预算区间/主要竞争对手/决策人性格等）
    3. 写入 pending_profile_update 表（待确认状态）
    4. 高风险字段（预算/竞争对手/决策人性格）必须用户显式确认

    Args:
        customer_id: 客户 ID
        session_id: 会话 ID（可选，用于关联建议来源）

    Returns:
        List[dict]: 生成的建议列表
    """
    from app.database import SessionLocal
    from app.models import ConversationTurn, PendingProfileUpdate

    db = SessionLocal()
    try:
        # 获取最近 10 轮对话
        turns = db.query(ConversationTurn).filter(
            ConversationTurn.customer_id == customer_id
        ).order_by(ConversationTurn.created_at.desc()).limit(20).all()

        if not turns:
            return []

        # 构建对话摘要用于分析
        conversation_text = "\n".join([
            f"[{'用户' if t.role == 'user' else '助手'}]: {t.content}"
            for t in reversed(turns)
        ])

        # 调用 LLM 分析
        prompt = f"""分析以下客户对话记录，提取可用于更新客户画像的信息。

对话记录：
{conversation_text[:3000]}  # 限制长度

请返回 JSON 格式的建议（只返回确实能从对话中推断出的信息，不要过度推断）：
{{
    "suggestions": [
        {{
            "field_name": "字段名（如 preferences, competitors, budget 等）",
            "suggested_value": "建议的值",
            "ai_reasoning": "为什么建议这个更新（基于哪句对话）",
            "risk_level": "high" | "medium" | "low"  // 高风险字段需要用户确认
        }}
    ]
}}

注意：
- 高风险字段（budget, competitors, decision_cycle）只能给出 low confidence 建议
- preferences, customer_type, source 等字段可以是 medium risk
- 简单的事实性信息（如联系人姓名、邮箱）可以是 low risk
- 如果对话中没有足够信息推断某个字段，不要建议
- field_name 必须是 customer 表中存在的字段名"""

        try:
            result = await call_llm(prompt)
            # 解析 JSON
            import json
            result = result.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            analysis = json.loads(result.strip())
            suggestions = analysis.get("suggestions", [])
        except Exception as e:
            print(f"画像建议生成失败: {e}")
            return []

        # 写入 pending_profile_update 表
        saved_suggestions = []
        for sugg in suggestions:
            # 检查是否已有相同的 pending 建议
            existing = db.query(PendingProfileUpdate).filter(
                PendingProfileUpdate.customer_id == customer_id,
                PendingProfileUpdate.field_name == sugg.get("field_name"),
                PendingProfileUpdate.status == "pending"
            ).first()

            if existing:
                continue  # 跳过重复建议

            pending = PendingProfileUpdate(
                customer_id=customer_id,
                session_id=session_id,
                field_name=sugg.get("field_name"),
                suggested_value=sugg.get("suggested_value"),
                ai_reasoning=sugg.get("ai_reasoning", ""),
                status="pending"
            )
            db.add(pending)
            saved_suggestions.append(sugg)

        db.commit()
        return saved_suggestions

    finally:
        db.close()
