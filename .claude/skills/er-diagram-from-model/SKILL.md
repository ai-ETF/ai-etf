---
name: er-diagram-from-model
description: 根据关系模型 Markdown（er-model.md）生成或更新数据库 E-R 图 HTML。只要用户提到关系模型、关系模式、E-R 图 / ER 图、数据库结构页面、er-model.md，或者要求“按这份 md 更新数据库图”“把表结构画成 E-R 图”“把新表加进关系图”，就使用本 skill，即使用户没有明确说“用 skill”。它只替换 HTML 里的 DATA 数据对象，保留现有页面样式与交互。
---

# 关系模型 → E-R 图 HTML

把一份**关系模型** Markdown 当作唯一事实来源，更新一个已有 DATA 驱动的 E-R 页面。输入不是 SQL、不是 ORM 模型、也不是 E-R 图本身——是“表 + 字段 + 主键 + 外键”的文字版。

## 什么时候用

- 用户给了 `er-model.md` / 关系模型文档，要求生成或更新 E-R 图 HTML
- 数据库结构变了，需要同步页面上的表、字段、连线
- 用户说“按这份 md 改 HTML”“把新表加进 E-R 图”“重新画数据库图”

## 什么时候不用

- 只有 SQL migration、没有关系模型文档：先问用户是否要先把 SQL 整理成关系模型，不要直接解析 SQL
- 目标只是 Mermaid / PlantUML 文本图：用通用画图 skill
- 要改页面样式、交互、搜索逻辑：这不是本 skill 的范围

## 输入契约

完整格式见 `references/input-contract.md`。最低要求：

- `## 1. 业务分域`：每张表归入哪个域
- `## 2. 关系（表）`：每张表的主键、外键、字段表
- `## 5. 关系总表`：真实外键与逻辑引用的完整清单

如果用户给的是数据库字典（只有表和字段、没有外键），先指出缺外键，并参考 `references/input-contract.md` 补齐；不要用字段命名去猜外键。

## HTML 契约

完整结构见 `references/html-data-contract.md`。核心只有一句：**只替换 `const DATA={...}`，其余字节保持不动。**

## 工作流

先把 `$SKILL` 设成本 SKILL.md 所在目录。

1. **定位输入**：确认 md 路径和目标 HTML 路径。用户没说 HTML 就问一次，不要猜。
2. **解析 + 校验**
   ```bash
   python3 "$SKILL/scripts/parse_model.py" <model.md> --out /tmp/er-model.json
   python3 "$SKILL/scripts/validate_model.py" /tmp/er-model.json
   ```
   校验失败就停：把 ERROR 原样交给用户，不要改 HTML。
3. **生成 DATA**
   ```bash
   python3 "$SKILL/scripts/build_data.py" /tmp/er-model.json <target.html> --out /tmp/er-data.json
   ```
   读 stderr 的 `WARN 将从图中移除的表`。有移除先向用户确认；新增表会自动排版。
4. **先干跑**
   ```bash
   python3 "$SKILL/scripts/apply_data.py" <target.html> /tmp/er-data.json --dry-run
   ```
   核对 tables / columns / relationships 三个数字的变化方向。
5. **写入**
   ```bash
   python3 "$SKILL/scripts/apply_data.py" <target.html> /tmp/er-data.json
   ```
   脚本会自动备份为 `<target>.bak-YYYYmmddHHMMSS`。
6. **回归检查**
   ```bash
   python3 "$SKILL/scripts/check_roundtrip.py" /tmp/er-model.json <target.html>
   ```
   失败就回滚到备份，并把差异报告给用户。

## 铁律

1. **md 是唯一事实来源。** HTML 与 md 冲突时改 HTML，不改 md。
2. **只动 DATA。** 不碰 CSS、DOM、渲染函数；替换范围之外的字节必须逐字不变。
3. **结构归 md，展示归 HTML。** 表、字段、键、关系、域来自 md；坐标、颜色、行数、索引定义从 HTML 继承。
4. **真实外键和逻辑引用必须分开。** `relationships[].type` 只能是 `hard` 或 `logical`；页面上分别画实线和虚线，不能互相冒充。
5. **删表要确认。** md 少一张表意味着图上删一张表；先问，再写。
6. **校验不过不写文件。** 任何一步 exit code 非 0 都停。

## 常见错误

- 把 `auth.users` 当普通业务表：外部实体要写成 `#### \`auth.users\`（外部实体）`，只登记被引用的主键。
- 外键行漏了 `ON DELETE`：图上会显示成 NO ACTION。
- 表内的「外键」行与第 5 节关系总表不一致：以第 5 节为准，表内行只负责给字段打 FK 标记。
- 新表没写进任何域：校验会报「没有归入任何业务域」。
- 直接手改 HTML 的 DATA：下次从 md 重建会被覆盖。

## 输出给用户什么

一句话说清：表 / 列 / 外键 / 逻辑引用各增减多少，哪些表新增、哪些表被删，备份文件在哪。不要复述整份关系模型。
