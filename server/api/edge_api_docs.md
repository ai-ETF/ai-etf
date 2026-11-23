# Edge Function API 接口文档

## 概述

本文档描述了后端服务提供的用于处理来自Edge Function的文件处理请求的API端点。

## API 端点

### POST `/api/process-file-from-edge`

#### 功能描述

此端点用于处理来自Edge Function的文件处理请求。Edge Function负责验证用户权限和文件路径的一致性，然后将处理请求转发给后端服务。

#### 请求格式

```json
{
  "file_id": "string",
  "user_id": "string",
  "download_url": "string",
  "doc_type": "string (optional)",
  "parse_strategy": "object (optional)"
}
```

#### 请求参数说明

- `file_id` (必需): 文件在`files`表中的UUID
- `user_id` (必需): 用户在系统中的UUID
- `download_url` (必需): 文件的下载URL，短期有效，只用于本次处理
- `doc_type` (可选): 文档类型，默认为`general_document`
- `parse_strategy` (可选): 解析策略配置对象

#### 响应格式

```json
{
  "success": true,
  "document_id": "string"
}
```

#### 响应参数说明

- `success`: 处理是否成功
- `document_id`: 生成的文档记录在`documents`表中的UUID

#### 错误处理

- 400 Bad Request: 请求参数缺失或格式错误
- 500 Internal Server Error: 服务器内部错误

#### 使用示例

```bash
curl -X POST http://localhost:8000/api/process-file-from-edge \
  -H "Content-Type: application/json" \
  -d '{
    "file_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
    "user_id": "user123-4567-8901-2345-67890abcdef",
    "download_url": "https://your-storage-url.com/file-path?temporary-token",
    "doc_type": "financial_report",
    "parse_strategy": {
      "chunk_size": 1000,
      "overlap": 200
    }
  }'
```

## 处理流程

1. **下载文件**: 使用Edge Function提供的`download_url`下载文件内容
2. **创建documents记录**: 在`documents`表中创建记录，状态为`processing`
3. **内容解析与切分**: 解析文件内容并切分为语义块
4. **向量化**: 生成每个块的向量表示
5. **存储到document_chunks**: 将块和向量存储到`document_chunks`表
6. **更新状态**: 成功后更新`documents`表中的状态为`ready`

## 注意事项

- 此端点仅接受来自Edge Function的请求
- 不信任任何来自前端的`storage_path`
- 一个`file`可以创建多个`document`
- `document_chunks`表只允许`document_id`外键，不允许`file_id`
- 所有错误都会记录到`documents`表的`metadata`字段中