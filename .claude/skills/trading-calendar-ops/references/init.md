# 流程 C：首次初始化 / 新环境

**适用**：表不存在、`trading_calendar_state` 为空、`ready=false` 且从未成功刷新过。
已有数据的环境不要走本流程，直接走流程 B。

每个 bash 调用前先加载环境：

```bash
source /home/sing/ai-etf/.claude/skills/trading-calendar-ops/scripts/env.sh
```

## 步骤

1. 推送迁移（按 `db-migration` 技能；迁移会交互确认）：

   ```bash
   printf 'y\n' | supabase db push --linked
   supabase migration list --linked   # Local / Deployed 两列对齐
   ```

2. 配置 `ADMIN_API_TOKEN` 并重启服务（配置变更，按 `deploy` 技能；**重启前必须让用户确认**）。
3. 启动日志出现「交易日历快照未载入」属首次部署预期；依赖日历的业务接口此时返回 503。
4. 按 `annual-refresh.md` 先 dry_run、人工确认、再正式刷新。
5. status 确认 `ready=true`、`days/trading_days` 正常后，再做一次月度核验
   （`monthly-check.md`）。

> 启动补偿 `confirm_pending_orders(skip_trading_day_check=True)` 设计上不依赖日历，
> 所以「先补偿存量订单、后刷新日历」的顺序可以执行。
