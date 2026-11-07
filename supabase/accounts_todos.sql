-- ============================================================================
-- accounts 设计约束 / 待办（伪代码，不执行）
-- 列语义只在 accounts_rebuild.sql 的 COMMENT；本文件只放跨文件同步、
-- 待实现、待定三类条目。每条指向落地文件，不重复其内容。
-- ============================================================================

-- TODO-1  初始资金常量收敛为单一来源
--   INITIAL_CASH := config('account.initial_cash')     -- 唯一来源
--   accounts.cash DEFAULT                  := INITIAL_CASH
--   portfolio_service.INITIAL_CASH        := INITIAL_CASH
--   account_snapshot_service.INITIAL_CASH := INITIAL_CASH
--   约束：三处当前必须同值，调整初始资金时一并改。

-- TODO-2  账户创建唯一入口
--   ON INSERT auth.users    -> INSERT accounts(user_id)
--   ON place_purchase_order -> SELECT accounts FOR UPDATE
--                             NOT FOUND -> RAISE 'account missing'
--   落地：retire_lazy_account_creation.sql

-- TODO-3  资金分项维护动作
--   freeze      : cash -= a; frozen_cash += a
--   unfreeze    : frozen_cash -= a; cash += a
--   confirm_buy : frozen_cash -= a        (+ 尾差 cash += residual，契约待补)
--   confirm_sell: settling_cash += net
--   settle      : settling_cash -= net; cash += net
--   落地：accounts_tx_contract.sql（6 个 account_*，当前为骨架）

-- TODO-4  position_value 刷新
--   ON positions.quantity change -> account_refresh_position_value(user_id)
--   净值批量更新 -> 显式批量重算，不挂触发器
--   前提：先填函数实现，再启用触发器
--   落地：accounts_position_value_trigger.sql

-- TODO-5  对账扩展
--   reconcile_orders += settling_cash  vs SUM(net_amount WHERE status='settling')
--                     + position_value vs SUM(quantity × latest_unit_nav)

-- TODO-6  待定
--   set_updated_at() 同名覆盖：保留 REPLACE / 复用不定义 / 改名
--   全库金额精度统一 numeric(18,2)：后续表审到时同步，回来校 accounts_rebuild.sql
