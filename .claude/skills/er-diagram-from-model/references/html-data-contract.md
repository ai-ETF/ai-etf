# HTML 契约：DATA 数据对象

目标页面是**数据驱动**的：`<style>` 和渲染代码写死，页面内容全部来自页面里唯一的一个 `const DATA={...}`。所以 skill 的全部写操作只落在这一个对象字面量上。

## 支持哪些页面

只要页面里存在 `const DATA=` 且对象含 `domains` / `tables` / `relationships` / `positions` / `canvasHeights` / `summary` / `views` 七个键，就能用本 skill。

本项目当前两个文件都满足：

- `ai-etf-database-structure.html`（默认目标，多域分页视图）
- `ai-etf-er-diagram-final.html`（单页重绘版，用的是同一份 DATA）

如果 `apply_data.py` 报「没有找到完整的 const DATA={...}」，说明目标不是这套模板，**不要**用正则硬塞，停下来问用户。

## 七个顶层键

### `domains`

```json
{
  "id": "d1",
  "name": "用户",
  "no": "01",
  "color": "#2563eb",
  "desc": "用户身份、关注列表与资产配置模板。",
  "height": 600,
  "nodes": ["auth.users", "watchlist"],
  "relationships": ["watchlist_user_id_fkey"],
  "refs": ["fund"]
}
```

- `nodes`：本域页签上出现的表。
- `relationships`：两端都在本域内的关系 id。
- `refs`：额外的“幽灵节点”名单，用于本域没有出边、但仍想显示成外部卡片的表。渲染时真正决定画什么的是下面这条规则：

  > `renderER()` 取出**出发表属于本域**的所有关系（不分 `hard` / `logical`），把两端都加入节点集合，然后只渲染**在当前域 `positions` 里有坐标**的卡片。

  所以跨域关系的目标表必须在本域 `positions` 里有一个坐标，否则卡片和连线都会被静默跳过。`build_data.py` 会为这些目标自动补坐标。
- `relationships` 里放的 id 必须能在顶层 `relationships[].id` 中找到。

### `tables`

```json
{
  "watchlist": {
    "name": "watchlist",
    "domain": "d1",
    "cn": "用户自选列表",
    "kind": "table",
    "primary_key": ["id"],
    "columns": [
      {"name": "id", "type": "uuid", "nullable": false, "default": "gen_random_uuid()", "key": ["PK"]}
    ],
    "key_fields": ["user_id", "fund_code"],
    "unique_indexes": [
      {"name": "watchlist_pkey", "columns": ["id"], "predicate": null,
       "is_primary": true, "method": "btree", "definition": "CREATE UNIQUE INDEX ..."}
    ],
    "unique_constraints": [
      {"name": "watchlist_user_id_fund_code_key", "columns": ["user_id", "fund_code"],
       "definition": "UNIQUE (user_id, fund_code)"}
    ],
    "note": "",
    "schema": "public",
    "business_domain": "用户",
    "row_count": 1200
  }
}
```

- `kind`：`table` 或 `external_table`。外部实体（如 `auth.users`）走后者，默认折叠显示。
- `columns[].key`：取值 `PK`、`FK`、`UQ`，可同时出现。**UQ 只标真正的 UNIQUE 约束**；部分唯一索引不标，否则卡片上会误报。
- `default`、`row_count`、`note` 是展示信息，md 不管，从旧 HTML 继承。
- `key_fields` 是卡片上优先展示的几列；新表默认取非主键列的前 5 个。

### `relationships`

```json
{
  "id": "documents_file_id_fkey",
  "from": "documents",
  "from_cols": ["file_id"],
  "to": "files",
  "to_cols": ["id"],
  "type": "hard",
  "cardinality": "N:1",
  "on_delete": "CASCADE",
  "on_update": "NO ACTION",
  "note": "真实外键约束",
  "validated": true,
  "confidence": "declared",
  "name": "documents_file_id_fkey",
  "from_entity": "documents",
  "from_columns": ["file_id"],
  "to_entity": "files",
  "to_columns": ["id"]
}
```

- `type` 只有 `hard`（实线，有数据库约束）和 `logical`（虚线，无约束）。
- 同一对列故意冗余了两套字段名（`from_cols`/`from_columns`），因为页面里不同代码路径各读一套。**两套必须同时写。**
- 逻辑引用不要写 `validated` 键（写了 `null` 也会和旧数据不相等，导致回归对比失败）。
- `confidence`：真实外键 `declared`，逻辑引用 `inferred`。

### `positions` / `canvasHeights`

```json
"positions": {"d1": {"watchlist": [60, 70], "fund": [960, 70]}},
"canvasHeights": {"d1": 600}
```

- 坐标只存在于 HTML。**已有表保持原坐标**；新增表（含跨域幽灵节点）由 `auto_layout()` 排到该域已有卡片下方新起的一行，每行 4 张、列距 350、行距 190。
- 画布是手工摆的，间距并不规则，所以不要试图重建全局网格——`auto_layout()` 只做“在最低一行下面另起一行”，保证不与任何现有卡片重叠。
- `canvasHeights` 只增不减：新表落在下面时需要更高画布。

### `summary`

页面顶部统计卡直接读它：

```json
{
  "tables": 30, "entities": 31, "columns": 312,
  "hard": 31, "logical": 7, "authUserFks": 14,
  "views": 1, "viewColumns": 27,
  "uniqueIndexes": 41, "uniqueConstraints": 8, "partialUniqueIndexes": 3
}
```

- `entities` = 业务表 + 外部实体。
- `columns` 只数业务表，不数视图和外部实体。
- 后三个索引统计从 `tables` 反算，不由 md 提供。

### `views`

```json
{
  "name": "fund_catalog",
  "schema": "public",
  "kind": "view",
  "derived_from": ["fund", "fund_trade_rule"],
  "definition_options": {"security_invoker": "true"},
  "columns": [{"name": "fund_code", "type": "character varying(10)", "nullable": true, "default": null, "key": []}],
  "note": "仅包含 active 基金。"
}
```

## 哪些字段归 md，哪些归 HTML

| 归 md（会被覆盖） | 归 HTML（原样继承） |
|---|---|
| 表集合、表名、中文名 | 卡片坐标、画布高度 |
| 字段名、类型、可空 | 字段默认值 |
| 主键、外键、逻辑引用 | `row_count` |
| 业务域归属与域说明 | 域颜色 |
| 视图与枚举 | 索引的原始 `definition` 文本 |
| 全部 `summary` 数字 | 外部实体的 `note` |

冲突处理原则：**结构以 md 为准，展示以 HTML 为准。** 不要为了迁就旧坐标而改 md。

## 不可变区域

`const DATA={...}` 之外的一切——`<head>`、CSS、渲染函数、事件绑定、搜索逻辑、HTML 注释——都必须逐字节不变。`apply_data.py` 只替换 `{` 到匹配 `}` 之间的内容，写入前会把整份文件重新解析一遍逐值对比，不一致就拒绝写入。

## 备份与回滚

- 每次写入自动生成 `<target>.bak-YYYYmmddHHMMSS`。
- 回归失败时用最新备份覆盖回去：

```bash
cp "<target>.bak-<时间戳>" "<target>"
```

- `--dry-run` 只打印 `tables / columns / relationships` 的变化，不写文件，也不生成备份。
- `--no-backup` 仅供已在 git 或临时副本上操作的场景。

## 常见解析失败

| 报错 | 原因 |
|---|---|
| `没有找到完整的 const DATA={...}` | 页面不是这套模板，或 DATA 被改成了函数返回 |
| `写入前自检失败` | 生成的 JSON 含有页面无法还原的字符，通常是手工改了 data.json |
| 回归 `summary.columns` 不一致 | md 统计行没跟着字段增删更新 |
| 回归 `关系集合不一致` | 第 5 节关系总表与 md 表内「外键」行不同步 |
