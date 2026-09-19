-- 删除 auth 用户（含 identities），用于注销账号时的兜底。
--
-- 背景：admin.delete_user 对 sign_up 注册的用户（其 identity 的 email_verified=true）
-- 会返回「User not allowed」，导致 delete_account 的「删账号」步骤失败、邮箱被占用。
-- 此函数直接删 auth.identities + auth.users，绕过该限制。
--
-- 安全：SECURITY DEFINER 以函数 owner（postgres）身份执行；仅授权 service_role，
-- 普通用户（anon/authenticated）无法调用，避免任意删号。
CREATE OR REPLACE FUNCTION public.delete_auth_user(p_user_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  DELETE FROM auth.identities WHERE user_id = p_user_id;
  DELETE FROM auth.users WHERE id = p_user_id;
$$;

REVOKE ALL ON FUNCTION public.delete_auth_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.delete_auth_user(uuid) TO service_role;
