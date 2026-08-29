-- 注销账号：在单个事务内清理用户全部业务数据
-- 由后端在 admin.delete_user 之前调用（多张表 FK 指向 auth.users，必须先删业务数据再删账号）
-- 子表 document_chunks / message_chunks 由外键 ON DELETE CASCADE 自动清理。

CREATE OR REPLACE FUNCTION public.purge_user_data(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_deleted integer;
BEGIN
    -- 1) 会话：先 messages（级联 message_chunks），再 chats
    DELETE FROM public.messages WHERE user_id = p_user_id;
    DELETE FROM public.chats WHERE user_id = p_user_id;

    -- 2) 文档：先 documents（级联 document_chunks）；
    --    files 因自引用 parent_id（files_parent_id_fkey，无级联）需逐层删叶子节点
    DELETE FROM public.documents WHERE user_id = p_user_id;
    LOOP
        DELETE FROM public.files
        WHERE user_id = p_user_id
          AND id NOT IN (
              SELECT parent_id FROM public.files
              WHERE user_id = p_user_id AND parent_id IS NOT NULL
          );
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        EXIT WHEN v_deleted = 0;
    END LOOP;

    -- 3) 风险画像：先 profiles（fk_risk_profiles_answer 指向 answers），再 answers
    DELETE FROM public.user_risk_profiles WHERE user_id = p_user_id;
    DELETE FROM public.user_risk_answers WHERE user_id = p_user_id;

    -- 4) 其余平级表
    DELETE FROM public.user_allocations WHERE user_id = p_user_id;
    DELETE FROM public.watchlist WHERE user_id = p_user_id;
    DELETE FROM public.positions WHERE user_id = p_user_id;
    DELETE FROM public.trade_flow WHERE user_id = p_user_id;
    DELETE FROM public.trade_orders WHERE user_id = p_user_id;

    -- 5) 账户：先快照再账户（account_snapshots 可能引用 accounts）
    DELETE FROM public.account_snapshots WHERE user_id = p_user_id;
    DELETE FROM public.accounts WHERE user_id = p_user_id;
END;
$$;

-- 授权：后端以 service_role key 通过 PostgREST 调用 RPC
GRANT EXECUTE ON FUNCTION public.purge_user_data(uuid) TO service_role;
