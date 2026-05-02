"""
VibeRAG 文档解析服务

两步式 Ingest 实现（规范 §8 P0）：
- Step 1：LLM 先分析文档结构类型（报价单表格/产品手册章节/合同条款/自由文本段落）
- Step 2：根据分析结果决定分块方式，按建议分块入库
"""
import hashlib
import re
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from app.config import settings


# 文档类型识别规则
DOC_TYPE_RULES = [
    # 报价单（优先级最高）
    {
        'type': 'quotation',
        'keywords': ['报价', '价格', '单价', 'quantity', 'quantity', 'price', 'quotation', 'quote',
                     'MOQ', '最小起订量', 'payment terms', '付款方式', '交货期', 'delivery'],
        'priority': 5,
    },
    # 成交记录
    {
        'type': 'contract',
        'keywords': ['合同', 'contract', '订单', 'order', '已售', 'sold', '出货', 'shipment',
                     '签约', '成交', 'invoice', '发票'],
        'priority': 4,
    },
    # 产品说明
    {
        'type': 'product',
        'keywords': ['规格', 'spec', '型号', 'model', 'material', '材料', '尺寸', 'dimension',
                     'parameter', '参数', '技术', 'technical', '认证', 'certificate', 'CE', 'UL', 'ISO'],
        'priority': 3,
    },
    # 客户资料
    {
        'type': 'customer',
        'keywords': ['联系人', 'contact', '公司', 'company', '地址', 'address', '电话', 'phone',
                     '邮箱', 'email', 'website', '网址'],
        'priority': 2,
    },
    # 沟通记录
    {
        'type': 'communication',
        'keywords': ['对话', 'chat', '邮件', 'email', '微信', 'wechat', '会议', 'meeting',
                     '沟通记录', 'discussion', 'correspondence'],
        'priority': 1,
    },
    # 样品信息
    {
        'type': 'sample',
        'keywords': ['样品', 'sample', '打样', 'prototype', '封样', 'approval sample', '确认'],
        'priority': 1,
    },
]


# ============================================================================
# 两步式 Ingest - Step 1: LLM 文档结构分析
# ============================================================================

async def analyze_document_structure(content: str, doc_type: str) -> Dict:
    """
    Step 1：LLM 分析文档结构，返回分块建议

    Args:
        content: 文档内容（前 2000 字用于分析）
        doc_type: 文档类型（来自 detect_doc_type）

    Returns:
        Dict: {
            "structure_type": "表格" | "章节" | "条款" | "段落",
            "chunk_suggestions": [
                {"start": 0, "end": 500, "type": "表格行", "description": "报价单第1行"},
                {"start": 500, "end": 1000, "type": "表格行", "description": "报价单第2行"},
            ],
            "overlap_tokens": 100-300,
            "reasoning": "分析理由"
        }
    """
    from app.services.rag import call_llm

    # 准备分析用的内容片段（限制长度）
    analysis_content = content[:2000]

    prompt = f"""分析以下{document_type}文档的结构，返回 JSON 格式的分块建议。

文档内容片段：
{analysis_content}

请返回以下 JSON 格式（不要包含其他内容）：
{{
    "structure_type": "表格结构" | "章节结构" | "条款结构" | "自然段落",
    "chunk_suggestions": [
        {{"start": 0, "end": 200, "type": "表格行/章节标题/条款/段落", "description": "简要描述"}}
    ],
    "overlap_tokens": 100-300之间的数字,
    "reasoning": "分析理由"
}}

规则：
- 报价单/价格表 → structure_type="表格结构"，每行/每列作为一个 chunk
- 产品手册/技术文档 → structure_type="章节结构"，按章节或标题分块
- 合同/协议 → structure_type="条款结构"，按条款分块
- 聊天记录/自由文本 → structure_type="自然段落"，按段落分块
- overlap_tokens：表格结构用 200-300，章节结构用 100，条款结构用 150
- 如果无法确定结构，返回 structure_type="自然段落" 作为默认值"""

    try:
        result = await call_llm(prompt)
        # 尝试解析 JSON
        # 去掉可能的 markdown 代码块标记
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]

        analysis = json.loads(result.strip())
        return analysis
    except (json.JSONDecodeError, Exception) as e:
        print(f"文档结构分析失败，使用默认分块: {e}")
        # 分析失败时返回默认分块策略
        return _get_default_chunk_suggestion(len(content), doc_type)


def _get_default_chunk_suggestion(content_length: int, doc_type: str) -> Dict:
    """获取默认分块建议（当 LLM 分析失败时）"""
    default_overlap = {
        'quotation': 200,
        'contract': 150,
        'product': 100,
        'customer': 100,
        'communication': 100,
        'sample': 100,
    }.get(doc_type, 100)

    return {
        "structure_type": "自然段落",
        "chunk_suggestions": [],
        "overlap_tokens": default_overlap,
        "reasoning": "LLM 分析失败，使用默认分块策略"
    }


# ============================================================================
# 两步式 Ingest - Step 2: 根据分析结果分块
# ============================================================================

def chunk_by_structure(content: str, analysis: Dict) -> List[Dict]:
    """
    Step 2：根据 LLM 分析结果进行智能分块

    Args:
        content: 完整文档内容
        analysis: analyze_document_structure 返回的分析结果

    Returns:
        List[Dict]: [{text, token_count, description, type}, ...]
    """
    structure_type = analysis.get("structure_type", "自然段落")
    overlap_tokens = analysis.get("overlap_tokens", 100)

    if structure_type == "表格结构":
        return _chunk_table_structure(content, analysis, overlap_tokens)
    elif structure_type == "章节结构":
        return _chunk_chapter_structure(content, analysis, overlap_tokens)
    elif structure_type == "条款结构":
        return _chunk_clause_structure(content, analysis, overlap_tokens)
    else:
        return _chunk_paragraph_structure(content, overlap_tokens)


def _chunk_table_structure(content: str, analysis: Dict, overlap_tokens: int) -> List[Dict]:
    """表格结构分块：按表格行或列分割"""
    chunks = []
    suggestions = analysis.get("chunk_suggestions", [])

    if suggestions:
        # 按 LLM 建议的分块位置分割
        for i, sugg in enumerate(suggestions):
            start = sugg.get("start", 0)
            end = sugg.get("end", min(start + 500, len(content)))
            text = content[start:end]

            if text.strip():
                chunks.append({
                    "text": text.strip(),
                    "token_count": count_tokens(text.strip()),
                    "description": sugg.get("description", f"表格第{i+1}部分"),
                    "type": sugg.get("type", "表格行")
                })
    else:
        # 默认：按行分割（用 | 或制表符分隔）
        lines = re.split(r'\n|(?:\||\t)+', content)
        current_chunk = []
        current_tokens = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_tokens = count_tokens(line)
            if current_tokens + line_tokens > settings.CHUNK_SIZE:
                if current_chunk:
                    chunks.append({
                        "text": '\n'.join(current_chunk),
                        "token_count": current_tokens,
                        "description": "表格结构块",
                        "type": "表格行"
                    })
                current_chunk = [line]
                current_tokens = line_tokens
            else:
                current_chunk.append(line)
                current_tokens += line_tokens

        if current_chunk:
            chunks.append({
                "text": '\n'.join(current_chunk),
                "token_count": current_tokens,
                "description": "表格结构块",
                "type": "表格行"
            })

    return chunks


def _chunk_chapter_structure(content: str, analysis: Dict, overlap_tokens: int) -> List[Dict]:
    """章节结构分块：按标题或章节分割"""
    chunks = []
    suggestions = analysis.get("chunk_suggestions", [])

    if suggestions:
        for i, sugg in enumerate(suggestions):
            start = sugg.get("start", 0)
            end = sugg.get("end", min(start + 800, len(content)))
            text = content[start:end]

            if text.strip():
                chunks.append({
                    "text": text.strip(),
                    "token_count": count_tokens(text.strip()),
                    "description": sugg.get("description", f"章节{i+1}"),
                    "type": sugg.get("type", "章节")
                })
    else:
        # 默认：按 # 标题或数字序号分割
        chapter_pattern = r'(?:#+\s*|\d+\.?\s*)[^\n]+'
        chapters = re.split(chapter_pattern, content)

        current_chunk = []
        current_tokens = 0

        for chapter in chapters:
            chapter = chapter.strip()
            if not chapter:
                continue

            chapter_tokens = count_tokens(chapter)
            if current_tokens + chapter_tokens > settings.CHUNK_SIZE:
                if current_chunk:
                    chunks.append({
                        "text": '\n'.join(current_chunk),
                        "token_count": current_tokens,
                        "description": "章节块",
                        "type": "章节"
                    })
                current_chunk = [chapter]
                current_tokens = chapter_tokens
            else:
                current_chunk.append(chapter)
                current_tokens += chapter_tokens

        if current_chunk:
            chunks.append({
                "text": '\n'.join(current_chunk),
                "token_count": current_tokens,
                "description": "章节块",
                "type": "章节"
            })

    return chunks


def _chunk_clause_structure(content: str, analysis: Dict, overlap_tokens: int) -> List[Dict]:
    """条款结构分块：按条款编号分割"""
    chunks = []
    suggestions = analysis.get("chunk_suggestions", [])

    if suggestions:
        for i, sugg in enumerate(suggestions):
            start = sugg.get("start", 0)
            end = sugg.get("end", min(start + 600, len(content)))
            text = content[start:end]

            if text.strip():
                chunks.append({
                    "text": text.strip(),
                    "token_count": count_tokens(text.strip()),
                    "description": sugg.get("description", f"条款{i+1}"),
                    "type": sugg.get("type", "条款")
                })
    else:
        # 默认：按条款编号分割（如"第1条"、"1."、"第一条"等）
        clause_pattern = r'(?:第[一二三四五六七八九十百千\d]+条|\d+\.\s*[^\n]+)'
        clauses = re.split(clause_pattern, content)

        current_chunk = []
        current_tokens = 0

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue

            clause_tokens = count_tokens(clause)
            if current_tokens + clause_tokens > settings.CHUNK_SIZE:
                if current_chunk:
                    chunks.append({
                        "text": '\n'.join(current_chunk),
                        "token_count": current_tokens,
                        "description": "条款块",
                        "type": "条款"
                    })
                current_chunk = [clause]
                current_tokens = clause_tokens
            else:
                current_chunk.append(clause)
                current_tokens += clause_tokens

        if current_chunk:
            chunks.append({
                "text": '\n'.join(current_chunk),
                "token_count": current_tokens,
                "description": "条款块",
                "type": "条款"
            })

    return chunks


def _chunk_paragraph_structure(content: str, overlap_tokens: int) -> List[Dict]:
    """自然段落分块：使用原有 chunk_text 逻辑"""
    text_chunks = chunk_text(content, overlap=overlap_tokens)
    return [
        {
            "text": chunk,
            "token_count": count_tokens(chunk),
            "description": "段落块",
            "type": "段落"
        }
        for chunk in text_chunks
    ]


# ============================================================================
# 文档类型识别
# ============================================================================


def detect_doc_type(filename: str, content: str = "") -> Tuple[str, float]:
    """
    检测文档类型

    Args:
        filename: 文件名
        content: 文件内容（可选）

    Returns:
        (doc_type, confidence)
    """
    filename_lower = filename.lower()
    content_lower = content.lower()

    scores = {}

    for rule in DOC_TYPE_RULES:
        doc_type = rule['type']
        keywords = rule['keywords']
        priority = rule['priority']

        score = 0

        # 文件名匹配
        for kw in keywords:
            if kw.lower() in filename_lower:
                score += priority * 2
                break

        # 内容匹配
        for kw in keywords:
            if kw.lower() in content_lower:
                score += priority
                break

        scores[doc_type] = score

    # 找出最高分
    if not scores or max(scores.values()) == 0:
        return 'other', 0.0

    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]

    # 计算置信度（归一化）
    confidence = min(max_score / 10.0, 1.0)

    return best_type, confidence


def count_tokens(text: str) -> int:
    """简单估算 token 数量（中英文混合）"""
    # 中文按字符计，英文按单词计
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其他字符
    other_chars = len(text) - chinese_chars - english_words

    # 粗略估算：中文约 1.5 token/字符，英文约 1.25 token/词
    return int(chinese_chars * 1.5 + english_words * 1.25 + other_chars * 0.5)


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """
    将文本分块

    Args:
        text: 原始文本
        chunk_size: 每块目标 token 数
        overlap: 重叠 token 数

    Returns:
        List[str]: 分块后的文本列表
    """
    if chunk_size is None:
        chunk_size = settings.CHUNK_SIZE
    if overlap is None:
        overlap = settings.CHUNK_OVERLAP

    # 按段落分割
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return [text]

    chunks = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        # 如果单个段落就超过 chunk_size，按句子分割
        if para_tokens > chunk_size:
            # 先保存当前 chunk
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                # 处理重叠
                overlap_text = '\n'.join(current_chunk)
                current_chunk = []
                current_tokens = 0

            # 按句子分割
            sentences = re.split(r'[。！？.!?\n]', para)
            sentences = [s.strip() for s in sentences if s.strip()]

            temp_chunk = []
            temp_tokens = 0

            for sent in sentences:
                sent_tokens = count_tokens(sent)
                if temp_tokens + sent_tokens > chunk_size:
                    if temp_chunk:
                        chunks.append(''.join(temp_chunk))
                    # 保持重叠
                    if overlap_text and len(temp_chunk) >= 2:
                        overlap_text = ''.join(temp_chunk[-2:])
                    temp_chunk = []
                    temp_tokens = 0

                temp_chunk.append(sent)
                temp_tokens += sent_tokens

            if temp_chunk:
                current_chunk = temp_chunk
                current_tokens = temp_tokens
        else:
            # 正常段落
            if current_tokens + para_tokens > chunk_size:
                # 保存当前 chunk
                chunks.append('\n'.join(current_chunk))

                # 保留重叠部分
                overlap_tokens = 0
                overlap_paras = []
                for para in reversed(current_chunk):
                    para_t = count_tokens(para)
                    if overlap_tokens + para_t <= overlap:
                        overlap_paras.insert(0, para)
                        overlap_tokens += para_t
                    else:
                        break

                current_chunk = overlap_paras + [para]
                current_tokens = overlap_tokens + para_tokens
            else:
                current_chunk.append(para)
                current_tokens += para_tokens

    # 添加最后一个 chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks


async def parse_file(file_record) -> List[dict]:
    """
    解析文件并分块（两步式 Ingest）

    Step 1: LLM 先分析文档结构类型
    Step 2: 根据分析结果决定分块方式

    Args:
        file_record: File 数据库记录

    Returns:
        List[dict]: 分块数据列表
    """
    file_path = file_record.file_path
    file_ext = file_record.file_ext.lower()

    # 选择解析器
    if file_ext == '.txt' or file_ext == '.md':
        content = await parse_txt(file_path)
    elif file_ext == '.pdf':
        # 先尝试用 PyMuPDF 提取文字
        content = await parse_pdf(file_path)
        # 如果没有提取到文字（或极少），尝试 OCR
        if not content or len(content) < 500:
            content = await parse_scanned_pdf(file_path)
    elif file_ext == '.docx':
        content = await parse_docx(file_path)
    elif file_ext == '.doc':
        content = await parse_doc(file_path)
    elif file_ext in ('.xlsx', '.xls'):
        content = await parse_excel(file_path)
    elif file_ext == '.xlt':
        content = await parse_xlt(file_path)
    elif file_ext == '.pptx':
        content = await parse_pptx(file_path)
    elif file_ext == '.ppt':
        content = await parse_ppt(file_path)
    elif file_ext in ('.png', '.jpg', '.jpeg', '.bmp'):
        # 图片文件使用 OCR
        content = await parse_image(file_path)
    elif file_ext == '.html':
        content = await parse_html(file_path)
    elif file_ext == '.csv':
        content = await parse_csv(file_path)
    elif file_ext == '.numbers':
        content = await parse_numbers(file_path)
    else:
        return []

    if not content:
        return []

    # 检测文档类型
    doc_type, confidence = detect_doc_type(file_record.file_name, content)
    file_record.doc_type = doc_type
    file_record.doc_type_confidence = confidence

    # Step 1: LLM 分析文档结构（两步式 Ingest）
    structure_analysis = await analyze_document_structure(content, doc_type)

    # Step 2: 根据分析结果分块
    structured_chunks = chunk_by_structure(content, structure_analysis)

    # 构建 chunk 数据
    chunks = []
    for i, chunk_item in enumerate(structured_chunks):
        chunk_hash = hashlib.md5(chunk_item['text'].encode()).hexdigest()
        chunks.append({
            'content': chunk_item['text'],
            'token_count': chunk_item.get('token_count', count_tokens(chunk_item['text'])),
            'chunk_index': i,
            'page_number': None,  # TODO: 从解析器获取
            'content_hash': chunk_hash,
            'chunk_type': chunk_item.get('type', '段落'),
            'chunk_description': chunk_item.get('description', ''),
        })

    return chunks


async def parse_txt(file_path: str) -> str:
    """解析 TXT 文件"""
    try:
        # 尝试不同编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
        content = None

        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            # 最后尝试二进制读取并忽略错误
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        return content.strip()
    except Exception:
        return ""


async def parse_md(file_path: str) -> str:
    """解析 MD 文件（与 TXT 类似）"""
    return await parse_txt(file_path)


async def parse_pdf(file_path: str) -> str:
    """
    解析 PDF 文件（文字型），优先使用 PyMuPDF

    Returns:
        str: 提取的文字，空白表示需要 OCR
    """
    try:
        import fitz  # PyMuPDF

        text_parts = []
        with fitz.open(file_path) as doc:
            for i, page in enumerate(doc):
                text = page.get_text()
                if text and text.strip():
                    text_parts.append(f"[Page {i+1}]\n{text.strip()}")

        result = '\n\n'.join(text_parts)

        # 检查是否为空或极少（< 500 字认为是扫描件）
        if len(result) < 500:
            # 返回空字符串，调用方会走 OCR
            print(f"PDF 文字提取极少（{len(result)}字），将尝试 OCR: {file_path}")
            return ""

        return result
    except ImportError:
        print(f"PDF 解析失败: {file_path}, error: PyMuPDF (fitz) 未安装，请运行: pip install pymupdf")
        return ""
    except Exception as e:
        print(f"PDF 解析失败: {file_path}, error: {e}")
        return ""


def is_scanned_pdf(file_path: str) -> bool:
    """
    判断 PDF 是否为扫描件（无文字层）

    判定逻辑：
    - 有任意一页 get_text() 有内容 → 不是扫描件
    - 所有页面 get_text() 为空，但有图片 → 扫描件
    - 所有页面 get_text() 为空，且无图片 → 空白/损坏
    """
    try:
        import fitz
        doc = fitz.open(file_path)
        for page in doc:
            if page.get_text().strip():
                return False  # 有文字，不是扫描件
            if page.get_images():
                return True   # 无文字但有图片，判定为扫描件
        return True  # 无文字无图片，视为空白/扫描件
    except Exception:
        return True  # 出错默认返回需要 OCR


async def parse_docx(file_path: str) -> str:
    """解析 DOCX 文件"""
    try:
        from docx import Document

        doc = Document(file_path)
        paragraphs = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        # 也提取表格
        for table in doc.tables:
            for row in table.rows:
                row_text = ' | '.join(cell.text.strip() for cell in row.cells)
                if row_text.strip():
                    paragraphs.append(row_text)

        return '\n\n'.join(paragraphs)
    except Exception as e:
        print(f"DOCX 解析失败: {file_path}, error: {e}")
        return ""


async def parse_excel(file_path: str) -> str:
    """解析 Excel 文件（支持 .xlsx 和 .xls）"""
    file_ext = Path(file_path).suffix.lower()

    try:
        if file_ext == '.xlsx':
            # 新版 Excel 格式
            import openpyxl
            text_parts = []
            wb = openpyxl.load_workbook(file_path, data_only=True)

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                text_parts.append(f"[Sheet: {sheet_name}]")

                for row in ws.iter_rows(values_only=True):
                    row_text = ' | '.join(str(cell) if cell is not None else '' for cell in row)
                    if row_text.strip():
                        text_parts.append(row_text)

                text_parts.append("")  # sheet 之间的空行

            return '\n'.join(text_parts)

        elif file_ext == '.xls':
            # 旧版 Excel 格式，使用 xlrd
            import xlrd
            text_parts = []
            wb = xlrd.open_workbook(file_path)

            for sheet_idx in range(wb.nsheets):
                sheet = wb.sheet_by_index(sheet_idx)
                text_parts.append(f"[Sheet: {sheet.name}]")

                for row_idx in range(sheet.nrows):
                    row_values = [str(cell) for cell in sheet.row_values(row_idx)]
                    row_text = ' | '.join(row_values)
                    if row_text.strip():
                        text_parts.append(row_text)

                text_parts.append("")

            return '\n'.join(text_parts)

    except ImportError:
        print(f"Excel 解析失败: {file_path}, error: xlrd 库未安装，请运行: pip install xlrd")
        return ""
    except Exception as e:
        print(f"Excel 解析失败: {file_path}, error: {e}")
        return ""


async def parse_pptx(file_path: str) -> str:
    """解析 PPTX 文件"""
    try:
        from pptx import Presentation

        prs = Presentation(file_path)
        text_parts = []

        for i, slide in enumerate(prs.slides):
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text = shape.text.strip()
                    if text:
                        slide_text.append(text)

            if slide_text:
                text_parts.append(f"[Slide {i+1}]\n" + '\n'.join(slide_text))

        return '\n\n'.join(text_parts)
    except Exception as e:
        print(f"PPTX 解析失败: {file_path}, error: {e}")
        return ""


async def parse_image(file_path: str) -> str:
    """
    使用 OCR 解析图片文件（PNG, JPG, JPEG, BMP）

    Args:
        file_path: 图片文件路径

    Returns:
        str: 提取的文字
    """
    try:
        import pytesseract
        from PIL import Image

        text_parts = []

        # 打开图片
        with Image.open(file_path) as img:
            # 如果是 PDF 页面，转换为 RGB
            if img.mode == 'RGBA' or img.mode == 'P':
                img = img.convert('RGB')

            # 使用 Tesseract OCR 提取文字
            # 指定中文+英文识别
            text = pytesseract.image_to_string(
                img,
                lang='chi_sim+eng',
                config='--psm 6'  # 假设统一文本块
            )

            if text.strip():
                text_parts.append(f"[图片 OCR 识别结果]\n{text}")

        return '\n'.join(text_parts) if text_parts else ""

    except ImportError:
        print(f"图片 OCR 解析失败: {file_path}, error: Pillow 或 pytesseract 未安装")
        return ""
    except Exception as e:
        print(f"图片 OCR 解析失败: {file_path}, error: {e}")
        return ""


async def parse_scanned_pdf(file_path: str) -> str:
    """
    使用 OCR 解析扫描型 PDF 文件

    Args:
        file_path: PDF 文件路径

    Returns:
        str: 提取的文字
    """
    try:
        import pytesseract
        from PIL import Image
        import pdfplumber

        text_parts = []

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # 尝试提取文字
                text = page.extract_text()

                if text and text.strip():
                    # 如果有文字，可能是混合型 PDF
                    text_parts.append(f"[Page {i+1}]\n{text}")
                else:
                    # 如果没有文字，尝试 OCR
                    try:
                        # 将 PDF 页面转换为图片
                        pix = page.get_pixmap(matrix=2.0)  # 2x 分辨率
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        # OCR
                        ocr_text = pytesseract.image_to_string(
                            img,
                            lang='chi_sim+eng',
                            config='--psm 6'
                        )

                        if ocr_text.strip():
                            text_parts.append(f"[Page {i+1} - OCR]\n{ocr_text}")
                    except Exception as ocr_err:
                        print(f"PDF 页面 {i+1} OCR 失败: {ocr_err}")
                        continue

        return '\n\n'.join(text_parts) if text_parts else ""

    except ImportError:
        print(f"扫描 PDF OCR 解析失败: {file_path}, error: Pillow 或 pytesseract 未安装")
        return ""
    except Exception as e:
        print(f"扫描 PDF OCR 解析失败: {file_path}, error: {e}")
        return ""


# ============================================================================
# 老格式文件转换解析（LibreOffice）
# ============================================================================


async def parse_doc(file_path: str) -> str:
    """
    解析老格式 DOC 文件（通过 LibreOffice 转换为 DOCX 再提取）

    Args:
        file_path: DOC 文件路径

    Returns:
        str: 提取的文字
    """
    import subprocess
    from pathlib import Path

    docx_path = file_path + 'x'  # .doc → .docx

    try:
        # 检查 LibreOffice 是否可用
        result = subprocess.run(
            ['soffice', '--headless', '--convert-to', 'docx',
             '--outdir', str(Path(file_path).parent), file_path],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"DOC 转换失败: {file_path}, error: {result.stderr}")

        if Path(docx_path).exists():
            content = await parse_docx(docx_path)
            # 删除临时转换文件
            try:
                Path(docx_path).unlink()
            except Exception:
                pass
            return content

        print(f"DOC 转换后文件不存在: {docx_path}")
        return ""

    except FileNotFoundError:
        print(f"DOC 解析失败: {file_path}, error: LibreOffice (soffice) 未安装")
        return ""
    except Exception as e:
        print(f"DOC 解析失败: {file_path}, error: {e}")
        return ""


async def parse_ppt(file_path: str) -> str:
    """
    解析老格式 PPT 文件（通过 LibreOffice 转换为 PPTX 再提取）

    Args:
        file_path: PPT 文件路径

    Returns:
        str: 提取的文字
    """
    import subprocess
    from pathlib import Path

    pptx_path = file_path + 'x'  # .ppt → .pptx

    try:
        result = subprocess.run(
            ['soffice', '--headless', '--convert-to', 'pptx',
             '--outdir', str(Path(file_path).parent), file_path],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"PPT 转换失败: {file_path}, error: {result.stderr}")

        if Path(pptx_path).exists():
            content = await parse_pptx(pptx_path)
            try:
                Path(pptx_path).unlink()
            except Exception:
                pass
            return content

        print(f"PPT 转换后文件不存在: {pptx_path}")
        return ""

    except FileNotFoundError:
        print(f"PPT 解析失败: {file_path}, error: LibreOffice (soffice) 未安装")
        return ""
    except Exception as e:
        print(f"PPT 解析失败: {file_path}, error: {e}")
        return ""


async def parse_xlt(file_path: str) -> str:
    """
    解析 Excel 模板文件 XLT（通过 LibreOffice 转换为 XLSX 再提取）

    Args:
        file_path: XLT 文件路径

    Returns:
        str: 提取的文字
    """
    import subprocess
    from pathlib import Path

    xlsx_path = file_path.replace('.xlt', '.xlsx')

    try:
        result = subprocess.run(
            ['soffice', '--headless', '--convert-to', 'xlsx',
             '--outdir', str(Path(file_path).parent), file_path],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"XLT 转换失败: {file_path}, error: {result.stderr}")

        if Path(xlsx_path).exists():
            content = await parse_excel(xlsx_path)
            try:
                Path(xlsx_path).unlink()
            except Exception:
                pass
            return content

        print(f"XLT 转换后文件不存在: {xlsx_path}")
        return ""

    except FileNotFoundError:
        print(f"XLT 解析失败: {file_path}, error: LibreOffice (soffice) 未安装")
        return ""
    except Exception as e:
        print(f"XLT 解析失败: {file_path}, error: {e}")
        return ""


# ============================================================================
# HTML 解析（BeautifulSoup）
# ============================================================================


async def parse_html(file_path: str) -> str:
    """
    用 BeautifulSoup 提取 HTML 正文文本

    Args:
        file_path: HTML 文件路径

    Returns:
        str: 提取的文字
    """
    try:
        from bs4 import BeautifulSoup

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        # 移除无关标签
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()

        text = soup.get_text(separator='\n', strip=True)

        # 合并空行
        lines = [l for l in text.split('\n') if l.strip()]
        return '\n'.join(lines)

    except ImportError:
        print(f"HTML 解析失败: {file_path}, error: beautifulsoup4 未安装，请运行: pip install beautifulsoup4")
        return ""
    except Exception as e:
        print(f"HTML 解析失败: {file_path}, error: {e}")
        return ""


# ============================================================================
# CSV 解析
# ============================================================================


async def parse_csv(file_path: str) -> str:
    """
    解析 CSV 文件

    Args:
        file_path: CSV 文件路径

    Returns:
        str: 提取的文字
    """
    import csv
    import codecs

    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']

    for enc in encodings:
        try:
            with codecs.open(file_path, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                results = []
                for row in reader:
                    row_text = ' | '.join(row)
                    if row_text.strip():
                        results.append(row_text)
                return '\n'.join(results)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"CSV 解析失败: {file_path}, error: {e}")
            return ""

    return ""


# ============================================================================
# Apple Numbers 解析
# ============================================================================


async def parse_numbers(file_path: str) -> str:
    """
    解析 Apple Numbers 文件（zip 打包的 XML 结构）

    Args:
        file_path: Numbers 文件路径

    Returns:
        str: 提取的文字
    """
    import zipfile

    texts = []

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            for name in zf.namelist():
                if name.endswith('.xml'):
                    content = zf.read(name).decode('utf-8', errors='ignore')
                    # 提取 Numbers 中的文字节点
                    matches = re.findall(r'<a:t>([^<]+)</a:t>', content)
                    texts.extend([m for m in matches if m.strip()])

        return '\n'.join(texts) if texts else ""

    except Exception as e:
        print(f"NUMBERS 解析失败: {file_path}, error: {e}")
        return ""
