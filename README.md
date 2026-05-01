# VibeRAG - 智能商业文档分析与销售助手

> 扫描客户文档目录，自动理解产品/报价/成交记录，AI 辅助写开发信、话术支持。

## 功能特性

### 文档库管理
- 指定本地目录路径，系统递归扫描所有文件（含子目录）
- 支持多种文档格式：
  - **v0.1**: TXT, MD, PDF（文字型）, DOCX
  - **v0.2**: XLSX, XLS, PPTX
  - **v0.3**: PNG, JPG, BMP（图片 OCR）, 扫描型 PDF（OCR）
- 增量扫描：首次全量扫描，后续自动跳过未变化文件
- 智能分块：按段落切分，保留上下文

### RAG 智能问答
- 基于文档内容进行自然语言问答
- 向量相似度检索（top_k=5，阈值 0.35）
- 每次回答附带引用来源文件名
- 未找到相关内容时明确提示，不编造答案

### 文档类型自动识别
- 报价单（识别价格、数量、MOQ 等关键词）
- 成交记录（合同、订单、出货等）
- 产品说明（规格、型号、技术参数等）
- 客户资料（联系人、公司、地址等）
- 沟通记录（邮件、会议、微信等）

### 技术架构
- **后端**: FastAPI + SQLAlchemy + SQLite
- **向量存储**: sqlite-vec（纯 Python 实现）
- **Embedding**: Ollama + nomic-embed-text（本地运行）
- **LLM 支持**: OpenAI / Claude / 硅基流动 / MiniMax 等 OpenAI 兼容 API

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/chefroger/viberag.git
cd viberag
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 或
.\venv\Scripts\activate   # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装 Ollama（Embedding 需要）

macOS:
```bash
brew install ollama
```

Linux:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Windows: 从 [ollama.com](https://ollama.com) 下载安装

### 5. 下载 Embedding 模型

```bash
ollama pull nomic-embed-text
```

### 6. 安装 OCR 支持（可选，v0.3 功能）

macOS:
```bash
brew install tesseract tesseract-lang
```

### 7. 配置 LLM API Key

首次启动后，在设置页面配置你的 LLM API Key。

## 运行

```bash
python run.py
```

浏览器打开 http://localhost:8000

## 使用流程

1. **创建文档库**: 点击"新建文档库"，填入本地目录路径
2. **等待扫描**: 系统自动扫描并索引文档（可在后台运行）
3. **开始问答**: 选择文档库后，直接用中文提问

## 项目结构

```
viberag/
├── app/
│   ├── main.py           # FastAPI 应用入口
│   ├── config.py          # 配置管理
│   ├── database.py        # 数据库连接
│   ├── models.py          # SQLAlchemy 模型
│   ├── routers/           # API 路由
│   │   ├── library.py    # 文档库管理 API
│   │   ├── settings.py    # 设置 API
│   │   └── ask.py         # 问答 API
│   └── services/          # 业务逻辑
│       ├── scanner.py     # 目录扫描
│       ├── parser.py      # 文档解析
│       ├── embedder.py    # 向量化
│       ├── vectorstore.py # 向量存储
│       └── rag.py         # RAG 问答
├── templates/
│   └── index.html         # 前端页面
├── static/
│   └── css/               # 样式文件
├── requirements.txt       # Python 依赖
└── run.py                 # 启动脚本
```

## 配置说明

### 环境变量（可选）

```env
# LLM 配置
LLM_PROVIDER=openai  # openai / anthropic / custom
LLM_API_KEY=your-api-key
LLM_API_BASE_URL=https://api.openai.com/v1  # 可选，自定义 API 地址
LLM_MODEL=gpt-4o-mini

# Ollama 配置
OLLAMA_HOST=http://localhost:11434

# 向量检索配置
TOP_K=5
SIMILARITY_THRESHOLD=0.35
```

### 数据目录

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/VibeRAG/` |
| Windows | `%APPDATA%/VibeRAG/` |
| Linux | `~/.vibrag/` |

数据库文件: `library.db`

## 版本历史

- **v0.21**: 基础 RAG 闭环，支持目录扫描、文档解析、向量检索、问答
- **v0.22**: 支持 .xls 旧版 Excel、图片 OCR、强制重扫

## License

MIT
