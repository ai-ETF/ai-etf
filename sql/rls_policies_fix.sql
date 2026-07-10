-- RLS 修复脚本：为缺失 RLS 的 8 张表添加行级安全策略
-- 在 Supabase SQL Editor 中执行
-- 解决 Supabase Database Linter 报错：rls_disabled_in_public + sensitive_columns_exposed

-- ============================================================
-- 1. message_chunks 表：通过消息链关联到 user_id
--    message_chunks → messages → chats → user_id
-- ============================================================
ALTER TABLE message_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己消息的切片" ON message_chunks
  FOR SELECT USING (
    message_id IN (
      SELECT m.id FROM messages m
      JOIN chats c ON c.id = m.chat_id
      WHERE c.user_id = auth.uid()
    )
  );

CREATE POLICY "用户创建自己消息的切片" ON message_chunks
  FOR INSERT WITH CHECK (
    message_id IN (
      SELECT m.id FROM messages m
      JOIN chats c ON c.id = m.chat_id
      WHERE c.user_id = auth.uid()
    )
  );

CREATE POLICY "用户删除自己消息的切片" ON message_chunks
  FOR DELETE USING (
    message_id IN (
      SELECT m.id FROM messages m
      JOIN chats c ON c.id = m.chat_id
      WHERE c.user_id = auth.uid()
    )
  );

-- ============================================================
-- 2. ai_requests 表：系统日志表，无 user_id
--    所有认证用户可读，写入由 service_role 处理
-- ============================================================
ALTER TABLE ai_requests ENABLE ROW LEVEL SECURITY;

CREATE POLICY "认证用户可查看AI请求日志" ON ai_requests
  FOR SELECT USING (auth.role() = 'authenticated');

-- ============================================================
-- 3. risk_questionnaires 表：全局问卷配置，无 user_id
--    所有认证用户可读，写入由 service_role 处理
-- ============================================================
ALTER TABLE risk_questionnaires ENABLE ROW LEVEL SECURITY;

CREATE POLICY "认证用户可查看风险问卷" ON risk_questionnaires
  FOR SELECT USING (auth.role() = 'authenticated');

-- ============================================================
-- 4. user_risk_answers 表：有 user_id，按用户隔离
-- ============================================================
ALTER TABLE user_risk_answers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己的风险答题" ON user_risk_answers
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "用户创建自己的风险答题" ON user_risk_answers
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "用户更新自己的风险答题" ON user_risk_answers
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "用户删除自己的风险答题" ON user_risk_answers
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 5. user_risk_profiles 表：有 user_id，按用户隔离
-- ============================================================
ALTER TABLE user_risk_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己的风险画像" ON user_risk_profiles
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "用户创建自己的风险画像" ON user_risk_profiles
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "用户更新自己的风险画像" ON user_risk_profiles
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "用户删除自己的风险画像" ON user_risk_profiles
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 6. market_indicators 表：全局市场数据，无 user_id
--    所有认证用户可读，写入由 service_role 处理
-- ============================================================
ALTER TABLE market_indicators ENABLE ROW LEVEL SECURITY;

CREATE POLICY "认证用户可查看市场指标" ON market_indicators
  FOR SELECT USING (auth.role() = 'authenticated');

-- ============================================================
-- 7. allocation_models 表：全局配置模型，无 user_id
--    所有认证用户可读，写入由 service_role 处理
-- ============================================================
ALTER TABLE allocation_models ENABLE ROW LEVEL SECURITY;

CREATE POLICY "认证用户可查看资产配置模型" ON allocation_models
  FOR SELECT USING (auth.role() = 'authenticated');

-- ============================================================
-- 8. user_allocations 表：有 user_id，按用户隔离
-- ============================================================
ALTER TABLE user_allocations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己的资产配置" ON user_allocations
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "用户创建自己的资产配置" ON user_allocations
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "用户更新自己的资产配置" ON user_allocations
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "用户删除自己的资产配置" ON user_allocations
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 完成说明：
-- 1. 有 user_id 的表（user_risk_answers, user_risk_profiles, user_allocations）
--    → 按 auth.uid() = user_id 隔离，用户只能操作自己的数据
--
-- 2. 无 user_id 的全局数据表（risk_questionnaires, market_indicators, allocation_models）
--    → 认证用户可读，写入由 service_role key 处理
--
-- 3. 系统日志表（ai_requests）
--    → 认证用户可读，写入由 service_role key 处理
--
-- 4. 关联表（message_chunks）
--    → 通过消息链（message → chat → user_id）关联到用户
--
-- 5. service_role key 始终绕过 RLS，后台服务不受影响
-- ============================================================
