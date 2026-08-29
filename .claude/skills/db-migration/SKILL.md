---
name: db-migration
description: 本仓库数据库结构与基础数据的变更操作规范（Supabase CLI 迁移机制）。当需要建表/改表/加索引/RLS/函数/枚举、新增或修改基础数据（费率规则/风险等级/配置字典）、数据库结构变更后同步类型定义，或处理 Supabase 网页端(Dashboard)直接改库后的同步时使用。
---

# 数据库迁移

本仓库使用 **Supabase CLI 迁移** 管理数据库结构（替代旧 `sql/` 手工脚本，均已归档至 `docs/legacy_sql/`）。

## 核心流程（最常用路径，直接执行）

```bash
supabase migration new <描述>                        # 1. 生成迁移文件
# 编辑 supabase/migrations/{时间戳}_{描述}.sql         # 2. 写 CREATE/ALTER/INSERT
supabase db push --linked                            # 3. 应用到远端
supabase migration list --linked                     # 4. 校验 Local │ Deployed 两列对齐
supabase gen types typescript --project-id "wiynpkkfsiiqnofhifhs" > server/types/supabase.ts  # 5. 同步前端类型
```

> ⚠️ `db push` 会**交互确认**（`Do you want to push...? [Y/n]`）。在非交互/后台环境（Claude 工具、CI）执行会挂起且无输出，需管道喂入确认：
> ```bash
> printf 'y\n' | supabase db push --linked
> ```

## 场景路由（渐进式披露：按需读，不必一次读全）

| 需要处理 | 读取文件 |
|---|---|
| 迁移机制基础：目录、环境要求、历史表、`migration repair` 对齐 | [references/01-工作流基础.md](references/01-工作流基础.md) |
| 建表 / 改表 / 加基础数据 / 网页端同步 / 类型同步的**逐步操作** | [references/02-日常场景操作手册.md](references/02-日常场景操作手册.md) |

> references/ 与 `docs/` 下两份同名文档内容一致，修改任一处需保持同步。

## 红线（任何情况下不得违反）

- ❌ 不改动基线迁移 `supabase/migrations/20260819113859_remote_schema.sql`
- ❌ 不修改已 push 的迁移文件；改错了**新建**迁移修正
- ❌ 不使用 `_run_sql.py` / `sql/` 目录执行 SQL（已废弃）
- ❌ 不把**用户业务数据**（交易/持仓/聊天）写进迁移文件
