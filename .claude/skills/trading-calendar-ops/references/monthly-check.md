# 流程 A：月度核验（只读）

**适用**：用户说「检查/核验日历」「日历是不是正常」「确认某个日期是否交易日」。
全程不写库、不触上游。默认抽查下个自然月；用户指定日期时用 `--from/--to` 限定。

每个 bash 调用前先加载环境（shell 状态不跨调用保留）：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
```

## A1. 查进程内状态与 DB 状态

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH "$TOKEN curl -sS -H \"X-Admin-Token: \$TOKEN\" http://127.0.0.1:8000/api/admin/trading-calendar/status | python3 -m json.tool"
```

关注：`ready`、`coverage_start`、`coverage_end`、`last_success_at`、`last_error`、`days`、`trading_days`。
`ready=false` 时不要查日期结论，转 `troubleshooting.md`。

## A2. 查库做机械性核验

把脚本通过 SSH 管道传给服务器上的项目解释器（脚本不用先部署）：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH 'cd /root/ai-etf && .venv/bin/python -' < "$SKILL_DIR/scripts/verify_calendar.py"
```

指定区间（例如确认某一天）：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH 'cd /root/ai-etf && .venv/bin/python - --from 2027-01-04 --to 2027-01-04' < "$SKILL_DIR/scripts/verify_calendar.py"
```

脚本的机械性检查（只读）：

- state 是否有覆盖区间、是否与主表 min/max 一致；
- 覆盖区间内是否每个自然日都有且仅有一行（断档）；
- 是否有周六/周日被标成交易日；
- `coverage_end` 是否距今天 ≥ 45 天、`last_success_at` 是否超过 400 天；
- 抽查区间内的非交易日按连续段列出，并标出其中的工作日（这些才是法定节假日）。

退出码 1 = 机械性检查失败；退出码 0 只代表「没有机械性异常」，**不代表数据正确**。

## A3. 交给人工判定

把 A1 + A2 的关键值整理成下面的格式，然后**停下来**，请人工对照公告确认。不要写「正常」。

```
交易日历核验（YYYY-MM-DD）
- ready: true/false
- 覆盖区间: <start> .. <end>
- 最近成功: <last_success_at>
- 规模: <days> 行 / <trading_days> 交易日
- 机械性检查: 通过 / 未通过（列出问题）
- 抽查区间非交易日:
    ...（脚本输出原样贴，保留「含工作日 → 需对照公告」标记）
- 待人工确认: 上面「含工作日」的区间是否与国务院/交易所公告一致
```

判定标准与异常处置见 `docs/40-运维/交易日历/交易日历运维手册.md` §3–§5；
人工确认后的记录追加到同目录的 `交易日历核验记录.md`。
