# AI-ETF 智能分析系统

AI-ETF 是一个使用人工智能技术分析交易所交易基金(ETF)的项目。该项目旨在帮助投资者更好地理解和分析ETF市场趋势，提供基于文档的智能问答和对比分析功能。

## 项目概述

AI-ETF 是一个基于人工智能的ETF分析系统，利用RAG（检索增强生成）技术，能够对ETF文档进行智能解析、存储和问答。系统支持PDF等格式的文档上传，并能基于文档内容回答用户问题，特别适用于金融领域的文档分析和对比。

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
   ```bash
   poetry shell
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
   ```bash
   poetry run uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
   ```

### 3. Docker部署

1. 构建Docker镜像：
   ```bash
   docker build -t ai-etf-server .
   ```

2. 运行容器：
   ```bash
   docker run -p 8000:8000 ai-etf-server
   ```

## API接口说明

### 1. 文档上传接口
- **路径**: `POST /api/upload`
- **请求体**:
  ```json
  {
    "url": "string",
    "source": "string"
  }
  ```
- **响应**:
  ```json
  {
    "success": true,
    "doc_id": "string"
  }
  ```

### 2. 问答接口
- **路径**: `POST /api/ask`
- **请求体**:
  ```json
  {
    "question": "string",
    "doc_id": "string"
  }
  ```
- **响应**:
  ```json
  {
    "prompt": "string",
    "decision": {
      "intent": "string",
      "output_format": "string",
      "top_k": "number",
      "doc_filter": "string"
    },
    "top_chunks": [
      {
        "chunk_id": "string",
        "text": "string",
        "score": "number"
      }
    ]
  }
  ```

### 3. 测试接口
- **路径**: `GET /test/hello`
- **响应**:
  ```json
  {
    "message": "Hello World"
  }
  ```

## 使用示例

### 1. 文档上传
```bash
curl -X POST http://localhost:8000/api/upload \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/etf_report.pdf",
    "source": "etf_report"
  }'
```

### 2. 问答查询
```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "两只ETF基金的收益分配原则有什么不同？",
    "doc_id": "your_doc_id"
  }'
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
- `ETFSERVER_EMBED_DIM`: 嵌入向量维度（默认768）
- `ETFSERVER_DB_PATH`: 数据库路径（如果使用本地数据库）

## 日志系统

项目实现了全面的日志记录系统：
- 每个函数和方法都包含进入、执行过程和退出时的日志记录
- 记录关键函数的输入参数、中间结果和最终返回值
- 记录操作的数据量大小、处理数量及耗时等性能相关信息
- 增强异常捕获机制，确保错误堆栈和上下文信息被完整记录

## 项目规范

### 代码规范
- 使用Python 3.10+语法
- 遵循PEP 8代码风格
- 使用类型提示增强代码可读性
- 详细的日志记录便于调试

### 设计模式
- 使用工厂模式处理不同类型的文档
- 采用策略模式处理不同的分块策略
- 使用服务层模式分离业务逻辑和数据访问

## 贡献指南

欢迎提交Issue和Pull Request来改进项目。在提交代码前，请确保：
1. 代码遵循项目规范
2. 添加了适当的测试
3. 更新了相关文档
4. 通过了所有测试

## 许可证

本项目遵循MIT许可证，详情请见LICENSE文件。

## 致谢

本项目使用了多个开源项目，包括FastAPI、Supabase、Sentence Transformers等，感谢这些项目的贡献者。