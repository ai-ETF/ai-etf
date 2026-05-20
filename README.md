# AI-ETF 智能分析系统

AI-ETF 是一个使用人工智能技术分析交易所交易基金(ETF)的项目。该项目旨在帮助投资者更好地理解和分析ETF市场趋势，提供基于文档的智能问答和对比分析功能。

## 项目架构

```
ai-etf/
├── ai_etf/                    # 核心AI处理模块
│   ├── __init__.py
│   ├── test_read_two_pdf.ipynb   # Jupyter Notebook测试文件
│   └── test_read_two_pdf.py      # PDF处理核心模块
├── server/                    # Web API服务
│   ├── app.py                 # FastAPI应用入口
│   ├── agents/                # AI智能体模块
│   │   ├── question_agent.py  # 问题意图分析智能体
│   │   ├── document_agent.py  # 文档分析智能体
│   │   └── output_format_agent.py # 输出格式智能体
│   ├── api/                   # API路由定义
│   │   ├── ask.py             # 问答接口
│   │   ├── upload.py          # 文档上传接口
│   │   └── test.py            # 测试接口
│   ├── services/              # 业务逻辑服务
│   │   ├── document_service.py # 文档处理服务
│   │   └── qa_service.py      # 问答服务
│   ├── rag/                   # RAG组件
│   │   ├── chunker.py         # 文本分块器
│   │   ├── embedder.py        # 文本向量化器
│   │   ├── retriever.py       # 检索器
│   │   └── prompt_builder.py  # 提示词构建器
│   ├── storage/               # 数据存储模块
│   │   ├── document_repo.py   # 文档存储
│   │   ├── embedding_repo.py  # 向量存储
│   │   └── supabase_client.py # Supabase客户端
│   └── config/                # 配置模块
│       └── settings.py        # 系统配置
├── tests/                     # 测试模块
├── Dockerfile                 # Docker容器化配置
├── docker-compose.yml         # Docker Compose配置
├── downEmbeddingModules.py    # 下载嵌入模型脚本
├── pyproject.toml             # Poetry项目配置
├── poetry.lock                # Poetry依赖锁定
├── .env                       # 环境变量配置
├── .gitignore                 # Git忽略配置
└── README.md                  # 项目说明文档
```

## 核心功能

### 1. 文档智能解析
- 支持PDF、文本等多种格式文档的智能解析
- 使用[pdfplumber](file:///home/sing/smartAnalysisOfETF/ai-etf/.venv/lib/python3.10/site-packages/pdfplumber/__init__.py#L1-L103)和[pypdf](file:///home/sing/smartAnalysisOfETF/ai-etf/.venv/lib/python3.10/site-packages/pypdf/__init__.py#L1-L4)库进行PDF内容提取
- 自适应文本分块算法，保持语义完整性

### 2. 智能向量化处理
- 使用[text2vec-base-chinese](file:///home/sing/smartAnalysisOfETF/ai-etf/.venv/lib/python3.10/site-packages/sentence_transformers/__init__.py#L1-L23)模型进行中文文本向量化
- 采用余弦相似度进行语义匹配
- 支持批量向量化处理，提高效率

### 3. 智能体系统
- **QuestionAgent**: 分析用户问题意图（比较、摘要、趋势、通用）
- **DocumentAgent**: 分析文档类型和结构
- **OutputFormatAgent**: 确定输出格式
- **Retriever**: 执行向量检索

### 4. RAG系统
- 基于向量相似度的检索增强生成
- 支持多文档检索和对比分析
- 自动构建提示词以供AI生成回答

### 5. 数据存储
- 使用Supabase作为向量数据库
- 支持文档分块的高效存储和检索
- 支持按文档ID过滤检索

## 技术栈

- **Python 3.10+**: 主要开发语言
- **FastAPI**: Web框架，提供高性能API服务
- **Supabase**: 向量数据库和后端服务
- **Sentence Transformers**: 文本向量化模型
- **PyPDF**: PDF文档处理
- **PDFPlumber**: PDF内容提取
- **Scikit-learn**: 机器学习库，用于相似度计算
- **Poetry**: 依赖管理工具
- **Docker**: 容器化部署

## 安装与部署

### 1. 环境要求
- Python 3.10或更高版本
- Docker (可选，用于容器化部署)
- Poetry (依赖管理工具)

### 2. 安装步骤

1. 克隆项目到本地：
   ```bash
   git clone <repository-url>
   cd ai-etf
   ```

2. 安装 Poetry（如果尚未安装）：
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

3. 安装项目依赖：
   ```bash
   poetry install
   ```

4. 激活虚拟环境：
  - 查看激活方式，接着复制给出的指令激活就可以
   ```bash
   poetry env activate
   ```

5. 下载嵌入模型：
   ```bash
   python downEmbeddingModules.py
   ```
   
   > 注意：此步骤会下载中文文本向量化模型到本地，以便离线使用

6. 配置环境变量：
   - 复制 `.env.example` 为 `.env`
   - 配置Supabase相关参数（URL和API密钥）

7. 启动服务：

  - 没有激活环境时，运行：
   ```bash
   poetry run uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
   ```
   - 激活环境时，运行：
   ```bash
   uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
   ```

## 项目特点

### 1. 智能意图识别
系统能够自动识别用户问题的类型：
- **比较类问题**: 如"两只基金有什么不同？"，返回表格格式对比
- **摘要类问题**: 如"总结一下基金特点"，返回摘要信息
- **趋势类问题**: 如"未来发展趋势如何？"，返回趋势分析
- **通用问题**: 返回普通文本格式回答

### 2. 多文档处理
- 支持同时处理多个ETF文档
- 可以跨文档检索相关信息
- 支持文档级别的过滤检索

### 3. 高效向量检索
- 使用Supabase向量数据库进行高效相似度检索
- 支持按文档ID过滤检索结果
- 优化的相似度算法确保检索质量

### 4. 灵活的扩展性
- 模块化设计，易于扩展新功能
- 支持多种文档格式处理
- 可配置的分块策略和向量化参数

## 开发说明

### 依赖管理
项目使用Poetry进行依赖管理，主要依赖包括：
- `sentence-transformers`: 用于文本向量化
- `fastapi`: Web框架
- `supabase`: 数据库客户端
- `pypdf` 和 `pdfplumber`: PDF处理
- `scikit-learn`: 机器学习算法

### 添加新依赖
```bash
# 添加生产依赖
poetry add package-name

# 添加开发依赖
poetry add --group dev package-name
```

### 测试运行
```bash
poetry run pytest
```

## 配置说明

项目使用环境变量进行配置，主要配置项包括：
- `SUPABASE_URL`: Supabase数据库URL
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase服务角色密钥
