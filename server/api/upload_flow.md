# Upload API 流程图

## 请求格式

```json
{
  "url": "string",           // 必需，文档的URL地址
  "source": "string"         // 可选，文档来源标识
}
```

## 返回格式

```json
{
  "success": true,
  "doc_id": "string"         // 生成的文档唯一标识符
}
```

## 流程图

```mermaid
graph TD
    A[客户端发送POST请求到 /api/upload] --> B{验证请求参数}
    B -->|验证失败| C[返回HTTP 422错误]
    B -->|验证成功| D[创建DocumentService实例]
    D --> E[下载URL指向的文档]
    E -->|下载失败| F[返回HTTP 500错误]
    E -->|下载成功| G[检查内容类型]
    G -->|文本类型| H[直接使用下载的文本内容]
    G -->|非文本类型| I[创建二进制文件占位符]
    H --> J[生成UUID作为文档ID]
    I --> J
    J --> K[保存文档到DocumentRepo]
    K --> L[使用split_text分割文本]
    L --> M[为每个文本块生成嵌入向量]
    M --> N[将文本块和向量存储到EmbeddingRepo]
    N --> O[返回成功响应]
    O --> P[{"success": true, "doc_id": "文档ID"}]
    
    style A fill:#e1f5fe
    style P fill:#e8f5e8
    style F fill:#ffebee
    style C fill:#ffebee
```

## 详细流程说明

1. 客户端向 `/api/upload` 发送POST请求
2. FastAPI框架验证请求体格式，确保包含必需的URL字段
3. 创建DocumentService实例
4. 通过requests.get()下载URL指向的文档
5. 检查响应状态码，确保下载成功
6. 检查内容类型，决定如何处理文档内容
7. 生成UUID作为文档唯一标识符
8. 将原始文档信息保存到DocumentRepo（SQLite数据库）
9. 使用split_text函数将文档分割成文本块
10. 为每个文本块生成嵌入向量
11. 将文本块和对应的向量存储到EmbeddingRepo
12. 返回成功响应，包含success标志和文档ID
```