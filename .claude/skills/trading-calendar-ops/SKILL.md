---
name: trading-calendar-ops
description: 交易日历的运维操作：负责执行命令和查库；写库前必须停下让人工确认 diff，核验结论必须由人工对照国务院/交易所公告判定，AI 不得代替签字。
---

# 交易日历运维操作

## 先分清「执行」与「判定」

- **本技能负责执行**：调管理接口、跑只读核验、整理 diff、写库后复核。
- **人工负责判定**：数据是否与国务院节假日安排、上交所/深交所公告一致；是否允许正式写库。
- 配套人工手册：`docs/40-运维/交易日历/交易日历运维手册.md`（判定标准、升级路径）；
  核验记录写入同目录的 `交易日历核验记录.md`。

「接口返回成功」只证明数据拉到了，**不证明数据是对的**。核验输出必须整理给人工看，不能自己下「日历正常」的结论。

## 按场景读哪个文件

先判断用户要做什么，**只读对应的 reference**：

| 场景 | 读取 |
|---|---|
| 检查/核验日历、确认某个日期是否交易日、月末例行检查 | [`references/monthly-check.md`](references/monthly-check.md) |
| 年度拉取、跨年、`coverage_end` 不跨年、11–12 月刷新 | [`references/annual-refresh.md`](references/annual-refresh.md) |
| 新环境、表不存在、`state` 为空、首次刷新 | [`references/init.md`](references/init.md) |
| 接口报错、`CalendarUnavailable` / `CalendarOutOfCoverage`、启动载入失败 | [`references/troubleshooting.md`](references/troubleshooting.md) |

默认：用户只说「检查/核验日历」时走 `monthly-check.md`；只是问某一天，也走它（用 `--from/--to` 限定那一天）。
读完后按文件内的 A/B/C/D 顺序执行，不要凭记忆跳过步骤。

## 固定参数

| 项 | 值 |
|---|---|
| 服务器 | `47.113.220.182`（连接方式见 `cloud-server` 技能） |
| 部署目录 | `/root/ai-etf`（只在这里操作） |
| 服务 | `fastapi` |
| 状态接口 | `GET /api/admin/trading-calendar/status` |
| 刷新接口 | `POST /api/admin/trading-calendar/refresh`（`?dry_run=true` 只预览） |
| 鉴权 | 请求头 `X-Admin-Token`，值来自服务环境变量 `ADMIN_API_TOKEN` |
| 表 | `trading_calendar`（逐日）、`trading_calendar_state`（单行状态） |
| 源 | `sina_trade_date`（单源，不换源） |

## 命令环境

Bash 工具的 shell 状态不跨调用保留，**每次执行命令前先 source**：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
```

它提供 `$SSH`（连服务器）、`$TOKEN`（取管理凭证的命令前缀）、`$SKILL_DIR`（技能目录）。
各流程的命令块已包含这行，照抄即可。

**凭证规则**：token 只在远端 shell 内展开，**不打印、不写入文件、不进入输出**。
不要读取 `/root/ai-etf/.env` 的内容。如果用户自己提供 token，让他用 `!` 在终端里设置，不要贴到对话里。

## 全局人工闸门

- 正式写库前必须先 dry_run，并把 diff 完整展示给用户；**用户明确确认后才能 apply**。
- 核验结论最多写到「机械性检查通过，待人工确认」；不得代替人工判定数据正确。
- 写库后必须复核（stats 与 dry_run 一致、status 正常、库内核验通过），不能写完就结束。

## 红线

- ❌ 不打印、不落盘 `ADMIN_API_TOKEN`；不读取 `.env` 内容。
- ❌ 不跳过 dry_run 直接正式刷新。
- ❌ 没有用户明确确认，不执行正式写库。
- ❌ 不把「接口 200 / 源返回了数据」当成「日历正确」；最终判定必须由人工对照公告。
- ❌ 不在 422 / 解析类 502 上反复重试；不换源、不猜日期。
- ❌ 不为了刷新而重启服务；只有配置变更或人工改库后才需要重启，且重启前要用户确认。
- ❌ 只在 `/root/ai-etf` 操作，不在 `/root/ai-etf/ai-etf` 执行任何命令。
- ❌ 多 worker 时刷新只更新处理请求的进程；当前单进程部署，若将来改多 worker，必须重新评估这条。
