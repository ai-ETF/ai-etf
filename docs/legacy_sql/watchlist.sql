-- 自选股表创建脚本
-- 在 Supabase SQL Editor 中执行

-- 创建自选股表
CREATE TABLE IF NOT EXISTS watchlist (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100),
  sort_order INT DEFAULT 0,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(user_id, fund_code)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_code ON watchlist(fund_code);

-- 添加注释
COMMENT ON TABLE watchlist IS '用户自选股/关注列表';
COMMENT ON COLUMN watchlist.user_id IS '用户ID';
COMMENT ON COLUMN watchlist.fund_code IS '基金代码（如512890）';
COMMENT ON COLUMN watchlist.fund_name IS '基金名称（冗余存储）';
COMMENT ON COLUMN watchlist.sort_order IS '排序顺序';

-- 可选：启用 RLS（行级安全）
-- ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;

-- 可选：创建 RLS 策略（用户只能访问自己的自选股）
-- CREATE POLICY "Users can view own watchlist" ON watchlist
--   FOR SELECT USING (user_id = auth.uid());

-- CREATE POLICY "Users can insert own watchlist" ON watchlist
--   FOR INSERT WITH CHECK (user_id = auth.uid());

-- CREATE POLICY "Users can delete own watchlist" ON watchlist
--   FOR DELETE USING (user_id = auth.uid());