-- 场外基金「单日累计申购上限」列
--
-- 背景：基金准入判定原先只放行「开放申购」，把处于「限大额」状态的基金整只
-- 拒在白名单外。但「限大额」的真实语义是「开放申购 + 单日累计上限」，用户买入
-- 不超过上限的金额本应成交。要收进这批基金，就必须能存下并校验这个上限。
--
-- 数据来源：天天基金 FundMNBasicInformation 接口的 MAXSG 字段（实测
-- 012348 天弘恒生科技ETF联接A 为 1000，开放申购基金返回哨兵值 100000000000）。
-- 同步任务每日刷新该值 —— 限大额是基金公司的临时措施，会随时放开或收紧。
--
-- NULL = 无限额。现有 20 只种子基金均为开放申购，保持 NULL 即可。
ALTER TABLE "public"."fund_fee_rules"
  ADD COLUMN IF NOT EXISTS "max_purchase_amount" numeric(18,2);

COMMENT ON COLUMN "public"."fund_fee_rules"."max_purchase_amount" IS
  '单日累计申购上限（元），NULL=无限额；来自天天基金 MAXSG 字段，随白名单同步每日刷新';
