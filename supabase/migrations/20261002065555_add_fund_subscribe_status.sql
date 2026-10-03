-- 场外基金「申购状态」列
--
-- 背景：fund_fee_rules 原先只存费率，不存申购状态 —— 状态只在同步时用来决定
-- 「要不要写入这一行」，写完之后就丢了。这带来两个问题：
--
-- 1) 无法发现「限大额但取不到单日上限」的基金。此前这种基金被静默跳过，
--    只留一行 WARNING 日志（日志还不落盘），没有任何可查询的痕迹。
-- 2) 状态变化不生效。基金从「开放申购」变成「暂停申购」后，同步不会写它，
--    库里那行原封不动，基金依然可买。(见 docs/场外基金申购上限设计文档.md 5.5)
--
-- 解法：把状态如实落库，让「能不能买」由交易侧按状态判定，而不是由
-- 「同步有没有写这一行」隐式决定。这样：
--   SELECT fund_code, fund_name FROM fund_fee_rules
--   WHERE subscribe_status = '限大额' AND max_purchase_amount IS NULL;
-- 就是需要人工干预的基金清单。
--
-- 取值来自天天基金 jjfl 页「交易状态」小节的「申购状态」行
-- （server/services/fund_fee_source.py 的 fetch_jjfl 解析；
--  注意移动端接口的 SGZT 字段本项目并未采用）：
-- 开放申购 / 限大额 / 暂停申购 / 封闭期 / 认购期 / ...
-- NULL = 未同步（迁移前写入的存量行），交易侧按「开放申购」兼容处理。
--
-- 故意不加 CHECK 约束：取值直接来自外部数据源，天天基金新增一个状态值
-- （如「限大额」当初就是新加的）不应该导致同步写库全部失败。
ALTER TABLE "public"."fund_fee_rules"
  ADD COLUMN IF NOT EXISTS "subscribe_status" text;

COMMENT ON COLUMN "public"."fund_fee_rules"."subscribe_status" IS
  '申购状态（来自天天基金 jjfl 页「交易状态」）：开放申购/限大额可申购，其余状态仅可赎回；NULL=存量行，按开放申购处理，随白名单同步每日刷新';
