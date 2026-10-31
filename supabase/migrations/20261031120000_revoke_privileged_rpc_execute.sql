-- 收紧高危 RPC 的执行权限：purge_user_data / delete_auth_user 只允许 service_role 调用。
--
-- 问题：这两个函数是 SECURITY DEFINER（以 postgres 身份执行），函数体内不校验调用人。
-- 原先 delete_auth_user 迁移里写了 `REVOKE ALL ... FROM PUBLIC`，看似安全，但 Supabase
-- 对 public schema 下的新函数有默认权限（default privileges），会**显式**授予
-- anon / authenticated / service_role。`REVOKE ... FROM PUBLIC` 只撤销 PUBLIC 那一项，
-- 撤不掉这两条显式授权。实测 pg_proc.proacl 为：
--   delete_auth_user : postgres=X | anon=X | authenticated=X | service_role=X
--   purge_user_data  : =X | postgres=X | anon=X | authenticated=X | service_role=X
-- 后果：任何持有 anon key（前端会下发）的人都能直接 POST /rest/v1/rpc/purge_user_data
-- 并传入任意 uuid，清空该用户的全部业务数据；delete_auth_user 则能直接删除账号。
--
-- 修复：显式撤销 anon / authenticated 的 EXECUTE，只保留 service_role
--（后端与集成测试均以 service_role 身份调用这两个 RPC）。

REVOKE ALL ON FUNCTION public.purge_user_data(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.purge_user_data(uuid) TO service_role;

REVOKE ALL ON FUNCTION public.delete_auth_user(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_auth_user(uuid) TO service_role;
