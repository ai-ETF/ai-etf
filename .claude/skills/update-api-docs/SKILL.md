---
name: update-api-docs
disable-model-invocation: true
description: 后端接口开发完成后，同步更新 docs/api/ 的 API 测试文档。当新增/修改/删除 server/api/ 下的路由，需要写入接口测试指令、更新接口总览、校验文档与线上一致时使用。
---

# API 文档更新

改完 `server/api/` 路由后，把 `docs/api/` 测试文档同步到最新。线上地址 `https://ai-etf.xyz`（HTTPS）。

## 文档位置（唯一维护地 docs/api/）

- 文件清单、接口总览、废弃表、环境配置：见 `README.md`「模块导航」；模板见 `_template.md`
- 路径前缀 → 写入文件：`/`、`/api/test`、`/api/secure-chat/login` → `01-基础与认证.md`；其余 `/api/secure-chat` → `02-对话与会话.md`；`/api/market` → `03-行情.md`；`/api/watchlist` → `04-自选股.md`；`/api/portfolio` → `05-组合交易.md`；`/api/risk` → `06-风险测评.md`；`/api/upload` → `07-文档上传.md`

## 接口小节模板（详细版看 _template.md）

~~~markdown
## N. 接口名
**方法 / 路径：** `GET /api/xxx/{id}`（🔒 需JWT / - 公开 / X-User-Id 开发测试）
**curl 示例：** 用 `$API`/`$TOKEN`/`$AUTH`；中文 query 用 `--get --data-urlencode`，路径中文可直接用
**参数/请求体表：** 位置、类型、必需(✅/❌)、说明（与代码 Pydantic 模型一致）
**响应要点：** 只列关键字段
~~~

## 流程

1. 看变更：`git diff --stat server/api/`
2. 校验：`python docs/api/scripts/gen_index.py --url https://ai-etf.xyz`
   - ⚠️「线上存在但文档缺失」→ 按模板加到对应模块文件
   - ⚠️「文档引用了不存在的接口」→ 从模块文档移除可用示例，挪进 `README.md`「已废弃接口」表并注明替代方案
3. 更新 README 接口总览表（用 `gen_index.py --url ... --gen-table` 生成后替换）
4. 复跑步骤 2，确认两条 ✅ 无告警（可选：`bash docs/api/scripts/smoke_test.sh`）

## 红线

- 一个接口只出现一次；登录只在 01；以 `server/api/__init__.py` 实际注册为准（文件存在 ≠ 已注册，如 `simple_chat.py` 未注册就不写）
- 统一 `$API`/`$TOKEN`/`$AUTH`；不写死 IP、真实账号密码
- 废弃接口不放可用示例，只进 README 废弃表
- 不删其他模块内容、不把设计文档并入接口文档
