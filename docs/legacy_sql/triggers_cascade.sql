-- 级联删除触发器：删 chat 时自动清理 messages 和 message_chunks
-- 在 Supabase SQL Editor 中执行

-- 1. 创建触发器函数：删除 message 时级联删除 message_chunks
CREATE OR REPLACE FUNCTION delete_message_chunks_on_message_delete()
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM message_chunks WHERE message_id = OLD.id;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- 2. 创建触发器函数：删除 chat 时级联删除 messages
CREATE OR REPLACE FUNCTION delete_messages_on_chat_delete()
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM messages WHERE chat_id = OLD.id;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- 3. 绑定触发器：messages 表，删除前触发
DROP TRIGGER IF EXISTS trigger_delete_message_chunks ON messages;
CREATE TRIGGER trigger_delete_message_chunks
  BEFORE DELETE ON messages
  FOR EACH ROW
  EXECUTE FUNCTION delete_message_chunks_on_message_delete();

-- 4. 绑定触发器：chats 表，删除前触发
DROP TRIGGER IF EXISTS trigger_delete_messages ON chats;
CREATE TRIGGER trigger_delete_messages
  BEFORE DELETE ON chats
  FOR EACH ROW
  EXECUTE FUNCTION delete_messages_on_chat_delete();
