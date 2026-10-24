# 流程 D：故障处理

**适用**：管理接口返回异常、业务接口报 `CalendarUnavailable` / `CalendarOutOfCoverage`、
启动日志显示日历载入失败。

先看 status 的 `last_error` 和 `ready`，再看接口返回码：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
$SSH "$TOKEN curl -sS -H \"X-Admin-Token: \$TOKEN\" http://127.0.0.1:8000/api/admin/trading-calendar/status | python3 -m json.tool"
```

| 现象 | 原因 | 处理 |
|---|---|---|
| 400 缺少 `Idempotency-Key` | 请求没带幂等键 | 补上，值用时间戳即可 |
| 401 管理凭证无效 | token 不匹配 | 重新从服务环境变量取值；不要打印 token |
| 409 已有刷新在跑 | 进程内非阻塞锁 | 等前一个结束，不要并发重试 |
| 422 数据校验失败 | 源为空、数量 < 1000、覆盖区间非法、`coverage_end < today` | **不重试**；未写库，旧快照保留；检查源数据/解析 |
| 502 且 `tried=[]` | 域名熔断冷却中，本次**没有**请求上游 | 等冷却（60s 起，最长 30 分钟）再试；不要为绕过熔断重启，除非用户明确要求 |
| 502 且 `kind` 为 `TIMEOUT/HTTP_403/HTTP_429/HTTP_5XX/CONNECTION_ERROR` | 上游网络层失败 | 稍后重试；看 `state.last_error` |
| 502 且 `kind` 为 `EMPTY_PAYLOAD/PARSE_ERROR/SCHEMA_DRIFT/UNEXPECTED` | 源内容变化或代码异常 | **不要靠重试解决**；确认源是否改版/akshare 是否可用，人工核对 |
| 503 接口未启用 | 服务端没配 `ADMIN_API_TOKEN` | 配置环境变量并重启（配置变更，需用户确认） |
| 503 `CalendarUnavailable` | 快照未载入（DB 为空/读取失败） | `journalctl -u fastapi` 看载入失败原因；修复后走 `init.md` 或 `annual-refresh.md` |
| 503 `CalendarOutOfCoverage` | 查询日期超出覆盖区间，常见于跨年未拉取 | 走 `annual-refresh.md`；先 dry_run 确认 `coverage_end` |
| 504 拉取超时 | 适配器/整体超时，未写库 | 旧数据保留；看 `last_error`；稍后重试 |

**手工改库的边界**：直接 `UPDATE trading_calendar` 不会改变进程内存，必须重启才生效，
而且下一次成功刷新会整表覆盖。仅在交易所临时调整、源未同步、且用户明确要求时，
按人工手册 §5 处理；改完要重启并记录依据。
