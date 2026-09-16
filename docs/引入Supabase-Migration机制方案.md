# 引入 Supabase Migration 机制

## Context（背景）

项目目前通过手工 SQL 文件（`sql/` 目录下 22 个文件）管理数据库结构变更，并在需要时用根目录的 `_run_sql.py`（调用 pg-meta 接口）手动执行到远端 Supabase。这种方式无版本化、无执行历史、易漂移。目标是用 **Supabase CLI 官方 migration 机制**取代手工 SQL，建立「版本化的迁移历史 + 可重复执行」的数据库变更流程。

用户已确认三项决策：
1. 采用 **Supabase CLI 迁移**（`supabase/migrations/*.sql` 时间戳文件）
2. 现有 `sql/` 目录归档到 legacy 目录，不再参与迁移流程
3. **仅远端**工作流（不启用本地 Docker Postgres）

## 关键事实

- 项目为 Supabase (PostgreSQL)，代码用 `supabase` Python 客户端直连，无 ORM
- Supabase CLI v2.110.0 已安装；项目已链接远端 `wiynpkkfsiiqnofhifhs`（"ai-ETF"），但 `supabase db diff --linked` 报 `LegacyProjectNotLinkedError`，需重新 link
- `supabase/` 目录当前只有 `.temp/linked-project.json`，缺 `config.toml`、`migrations/`、`seed.sql`
- **本机无 Docker**（WSL2 未装 Docker Desktop）。因此 `db diff` / `db reset` / `supabase start` 不可用；但 `db pull`（migra 直连）、`db push`（迁移历史表）、`migration new/list/repair` 均不需 Docker，可用于「仅远端」工作流
- 代码实际使用表：`accounts`、`account_snapshots`、`positions`、`trade_flow`、`trade_orders`、`fund_fee_rules`、`watchlist`、`documents`、`document_chunks`、`chats`、`messages`、`risk_questionnaires`、`user_risk_answers`、`user_risk_profiles`
- `sql/` 下 22 个文件：20 个已跟踪、2 个未跟踪（`alter_fund_fee_rules_risk_level.sql`、`seed_fund_risk_levels.sql`）
- `supabase/.temp/linked-project.json` 已被 git 跟踪且未 ignore（本地链接状态，建议后续移出跟踪）

## 前置条件（需用户提供）

Supabase **数据库密码**（Postgres 密码，非 service_role key）。`link`/`pull`/`push` 都需它。用户可在会话中用 `! supabase ... -p <密码>` 自行交互执行，或提供给我。

## 实施步骤（按顺序）

### 1. 初始化 Supabase 迁移结构
- 在仓库根执行 `supabase init`，生成 `supabase/config.toml`、`supabase/migrations/`、`supabase/seed.sql`（`supabase/.temp/` 已有的 link 状态保留）
- 若 `init` 因已有 `supabase/` 目录报错，用 `supabase init --force`

### 2. 重新链接远端项目
- `supabase link --project-ref wiynpkkfsiiqnofhifhs`（带数据库密码 `-p`），修复 `LegacyProjectNotLinkedError`

### 3. 生成基线迁移（capture 现有 schema）
- `supabase db pull --linked --schema public`（默认 migra diff 引擎，直连远端、不需 Docker）
- 产出 `supabase/migrations/<timestamp>_remote_schema.sql`，包含 public schema 的表、函数、触发器、RLS 策略、FTS 配置等
- 人工 review 该文件，确认覆盖了上述所有业务表，并检查是否含必要的 `CREATE EXTENSION` 语句

### 4. 标记基线为「已应用」
- `db pull` 不写迁移历史表，因此必须把基线标记为已应用，否则后续 `db push` 会重复执行基线导致「表已存在」报错
- `supabase migration repair --status applied <基线version> --linked`（version 取迁移文件名时间戳前缀）

### 5. 归档旧 SQL 文件到 `/legacy_sql` 目录
- 新建 `docs/legacy_sql/` 目录（位于 `/docs` 下），将 `sql/` 下 22 个文件全部移入：
  - 20 个已跟踪文件用 `git mv sql/X.sql docs/legacy_sql/X.sql`
  - 2 个未跟踪文件用 `mv sql/X.sql docs/legacy_sql/X.sql`
- 删除空的 `sql/` 目录
- 保留作历史参考，不参与新迁移流程

### 6. Seed 数据（可选，建议）
- `db pull` 只含 schema 不含数据。当前参考数据（`fund_fee_rules` 费率表、风险等级表等）已在远端
- 用 `supabase db dump --linked --data-only --table fund_fee_rules --table <其他参考表>` 把当前真实参考数据导出到 `supabase/seed.sql`，保证可复现（幂等：`ON CONFLICT DO NOTHING`）
- 若认为现有 seed SQL 已过时，此步以 `db dump` 导出的现网数据为准，不沿用旧 `sql/*seed*.sql`

### 7. 文档 + 清理（可选）
- 在 `supabase/README.md` 写一段迁移工作流说明：`supabase migration new <name>` → 编辑 SQL → `supabase db push --linked`
- 追加 `.gitignore`（仅追加）：`supabase/.temp/`，并将 `supabase/.temp/linked-project.json` 移出 git 跟踪（`git rm --cached`）
- 弃用根目录 `_run_sql.py`（迁移流程取代它），保留或删除均可

## 后续日常变更流程（写入文档）

1. `supabase migration new <描述>` 生成 `supabase/migrations/<ts>_<描述>.sql`
2. 编辑该 SQL（DDL/ALTER 等）
3. `supabase db push --linked --password <密码>` 应用到远端并记录历史
4. `supabase migration list --linked` 校验本地与远端版本一致

## 验证方式

- `supabase migration list --linked`：确认本地迁移与远端历史表对齐（基线为 applied）
- 写一个无害测试迁移（如 `COMMENT ON TABLE accounts IS 'migration smoke test'`），`db push --linked` 后确认成功且出现在 `migration list` 远端历史中，随后用 `migration repair --status reverted` 或反向 SQL 回滚
- 用现有服务代码做一次只读查询（`supabase.table('accounts').select('*').limit(1)`）确认 schema 未被破坏

## 风险与注意

- 本机无 Docker → 无法用 `db diff`/`db reset`/`supabase start` 做离线校验；校验依赖 `migration list` 与人工 SQL review
- `db pull` 基线可能遗漏 Supabase 内部 schema（auth/storage）——这些本就不应纳入迁移，只拉 `public` 是正确行为
- 迁移历史表 `supabase_migrations.schema_migrations` 首次 push 时自动创建，属正常
- 全程遵循 CLAUDE.md：不读 `.env`、用 poetry 管依赖（本任务不改依赖）、不在 dev 分支直接开发（已在新分支 `feature/user-profile`）
