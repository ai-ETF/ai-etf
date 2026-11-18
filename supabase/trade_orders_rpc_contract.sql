-- ============================================================================
-- public.trade_orders RPC 重写契约（NOT IMPLEMENTED · 不执行）
--
-- 前提：旧库 RPC 全部弃用，按 trade_orders_rebuild.sql 的新结构重写。
-- 落地：用 CREATE OR REPLACE FUNCTION 重写完整函数体，随依赖表
--       （positions / position_lots / fund_nav / fund_nav_state / accounts）
--       审计一起提交；本文件不覆盖现有实现，避免半成品上线。
-- 范围：不新增 RPC；触发器只需 trg_trade_orders_set_updated_at（已在表结构文件）。
-- 不建空壳函数：这些名字都是现存 RPC，空壳会覆盖实现，令确认链路停摆。
-- ============================================================================

-- 下单
-- place_purchase_order
--   去掉 p_estimated_nav；client_order_id 必传，去掉判空分支
--   订单只写申请信息，成交结果不在本表
--   字段改名：fund_name_snapshot / effective_trade_date / expected_confirm_date
-- place_redeem_order
--   同上改字段名；amount 传 NULL 不再传 0；settle_date 必填
--   client_order_id 必传

-- 确认与到账
-- confirm_buy_order
--   pending → processing → completed
--   同事务写入 trade_flow（一条订单一条流水）；订单只推进状态
--   解冻走 account_confirm_purchase_cash
-- confirm_sell_order
--   processing → settling；amount 保持 NULL
--   同事务写入 trade_flow（一条订单一条流水）；不动 cash
-- settle_redeem_order
--   settling → settled；settled_at = now()
--   到账金额取 trade_flow(amount - fee) 入 cash
--   processing_at / processing_by 清空

-- 撤单 / 拒单 / 复核
-- cancel_trade_order           pending → cancelled，写 cancelled_at
-- reject_trade_order           → rejected，写 reject_reason
-- mark_order_manual_review     → manual_review
-- requeue_manual_review_order  manual_review → pending
-- reap_stale_processing        用 processing_at 判租约，回 pending 或 manual_review

-- 对账与清理
-- reconcile_orders             查询字段改名；新增 status 联动与金额精度对账项
-- purge_user_data              删除顺序不变（trade_orders 在 position_lots / trade_flow 之后）

-- 不在重写范围
-- acquire_confirm_run / heartbeat_confirm_run / finish_confirm_run
--   只操作 confirm_runs，不引用 trade_orders，保留
