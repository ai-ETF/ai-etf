-- RLS 行级安全策略：按 user_id 隔离数据访问
-- 在 Supabase SQL Editor 中执行

-- ============================================================
-- 1. chats 表：用户只能操作自己的会话
-- ============================================================
ALTER TABLE chats ENABLE ROW LEVEL SECURITY;

-- 查看自己的会话
CREATE POLICY "用户查看自己的会话" ON chats
  FOR SELECT USING (auth.uid() = user_id);

-- 创建会话（user_id 必须是自己）
CREATE POLICY "用户创建自己的会话" ON chats
  FOR INSERT WITH CHECK (auth.uid() = user_id);

-- 更新自己的会话
CREATE POLICY "用户更新自己的会话" ON chats
  FOR UPDATE USING (auth.uid() = user_id);

-- 删除自己的会话
CREATE POLICY "用户删除自己的会话" ON chats
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 2. messages 表：用户只能操作自己会话下的消息
-- ============================================================
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- 查看自己会话下的消息
DROP POLICY IF EXISTS "用户查看自己的消息" ON messages;
CREATE POLICY "用户查看自己的消息" ON messages
  FOR SELECT USING (
    chat_id IN (SELECT id FROM chats WHERE user_id = auth.uid())
  );

-- 创建消息（必须在自己的会话下）
DROP POLICY IF EXISTS "用户创建自己的消息" ON messages;
CREATE POLICY "用户创建自己的消息" ON messages
  FOR INSERT WITH CHECK (
    chat_id IN (SELECT id FROM chats WHERE user_id = auth.uid())
  );

-- 删除自己会话下的消息
DROP POLICY IF EXISTS "用户删除自己的消息" ON messages;
CREATE POLICY "用户删除自己的消息" ON messages
  FOR DELETE USING (
    chat_id IN (SELECT id FROM chats WHERE user_id = auth.uid())
  );

-- ============================================================
-- 3. files 表：用户只能操作自己的文件
-- ============================================================
ALTER TABLE files ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己的文件" ON files
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "用户创建自己的文件" ON files
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "用户删除自己的文件" ON files
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 4. documents 表：用户只能操作自己的文档
-- ============================================================
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己的文档" ON documents
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "用户创建自己的文档" ON documents
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "用户删除自己的文档" ON documents
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- 5. document_chunks 表：通过 document_id 关联 documents 的 user_id
-- ============================================================
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "用户查看自己文档的切片" ON document_chunks
  FOR SELECT USING (
    document_id IN (SELECT id FROM documents WHERE user_id = auth.uid())
  );

CREATE POLICY "用户创建自己文档的切片" ON document_chunks
  FOR INSERT WITH CHECK (
    document_id IN (SELECT id FROM documents WHERE user_id = auth.uid())
  );

CREATE POLICY "用户删除自己文档的切片" ON document_chunks
  FOR DELETE USING (
    document_id IN (SELECT id FROM documents WHERE user_id = auth.uid())
  );

-- ============================================================
-- 注意：service_role key 会绕过 RLS，后台管理任务不受限制
-- Supabase 客户端代码使用 service_role key，所以现有代码不受影响
-- 前端用户通过 anon key 访问时，RLS 会生效
-- ============================================================
