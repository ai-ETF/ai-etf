# 流程 B：年度刷新（写库，需人工闸门）

**适用**：每年 11–12 月年度拉取、`coverage_end` 不跨年、交易所公告后需要刷新。
本流程会写生产库；没有用户明确确认，只能做到 B3。

每个 bash 调用前先加载环境：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
```

## B1. 前置条件（不满足就停）

1. 国务院办公厅已发布**下一年**节假日安排（**由人工确认**，不要凭日期推断）；
2. **只有 dry_run 返回的 `coverage_end` ≥ 次年 1 月 1 日才允许正式写库**；
3. 最近没有其他刷新在跑（并发会返回 409）。

> 源没更新时 dry_run 仍会成功，只是 `coverage_end` 不变、`inserted=0`。
> 这时**不要 apply**，告诉用户「源尚未包含次年日期，按周复检」。

## B2. dry_run 并整理 diff

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH "$TOKEN curl -sS -X POST -H \"X-Admin-Token: \$TOKEN\" -H \"Idempotency-Key: \$(date +%s)-dryrun\" 'http://127.0.0.1:8000/api/admin/trading-calendar/refresh?dry_run=true' -o /tmp/tc-dryrun.json && echo saved:/tmp/tc-dryrun.json"
```

整理成人工可看的摘要：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH 'cd /root/ai-etf && .venv/bin/python - /tmp/tc-dryrun.json' < "$SKILL_DIR/scripts/summarize_diff.py"
```

摘要分四块：改判/删除、新增的非交易日（工作日）、新增交易日、新增周末。重点核对：

- **改判/删除**：任何一条都必须人工对照公告确认；无法确认则中止；
- **新增的非交易日（工作日）**：元旦、春节、清明、劳动、端午、中秋、国庆是否都在；
  调休的周六日必须仍是 `false`；
- `coverage_end` 是否真的跨到次年。

## B3. 人工闸门（必须停）

把摘要完整展示给用户，明确问「是否确认写库」。**只有用户明确确认后才能执行 B4**。
用户没有确认、或 diff 里有无法解释的改判/删除时，到此为止；旧快照原样保留。

## B4. 正式写库

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH "$TOKEN curl -sS -X POST -H \"X-Admin-Token: \$TOKEN\" -H \"Idempotency-Key: \$(date +%s)-apply\" 'http://127.0.0.1:8000/api/admin/trading-calendar/refresh' | python3 -m json.tool"
```

## B5. 写库后复核（不能省）

1. 正式调用的 `stats` 必须与 dry_run 一致；不一致说明期间源或 DB 变了，重新走 B2；
2. 再调一次 status，确认 `ready=true`、`coverage_end` 已前移、`last_error=null`、
   `last_success_at` 是刚才；
3. 跑一次库内核验（次年 1–3 月是关键区间）：

   ```bash
   source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
   $SSH 'cd /root/ai-etf && .venv/bin/python - --from 2027-01-01 --to 2027-03-01' < "$SKILL_DIR/scripts/verify_calendar.py"
   ```

4. 把 B2/B4/B5 的关键值交给人工确认，并追加到
   `docs/40-运维/交易日历/交易日历核验记录.md`。**不需要重启服务**：刷新在服务进程内替换内存快照。
