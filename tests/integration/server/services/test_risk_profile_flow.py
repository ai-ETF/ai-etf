"""P0-3 风险测评集成测试：RiskService ↔ 真实 Postgres（三表流转）。

模块名称：风险画像服务
所测功能：问卷读取、答案提交→画像计算→三表落库、upsert 语义、画像查询
使用的测试方法：本地 Supabase 栈 + 种子问卷 + 真实 auth 用户（user_risk_* 有 FK 到 auth.users）
"""
import pytest

pytestmark = pytest.mark.integration


def _answers(choice: str) -> list:
    """构造 5 道题全部选同一选项的答案（问卷共 q1~q5）。"""
    return [{"question_id": f"q{i}", "value": choice} for i in range(1, 6)]


def test_get_active_questionnaire_返回种子问卷(risk_service):
    q = risk_service.get_active_questionnaire()
    assert q is not None
    assert q["version"] == "v1.0"
    assert len(q["questions"]) == 5


def test_submit_全选A_保守型且三表落库(risk_service, supabase_client, auth_user_id):
    q = risk_service.get_active_questionnaire()
    r = risk_service.submit_answers(auth_user_id, q["id"], _answers("A"))
    assert r["success"] is True
    assert r["profile"]["risk_level"] == "conservative"

    # 三表真实落库：答案 + 画像各 1 条
    ans = supabase_client.table("user_risk_answers").select("*").eq("user_id", auth_user_id).execute().data
    assert len(ans) == 1
    prof = supabase_client.table("user_risk_profiles").select("*").eq("user_id", auth_user_id).execute().data
    assert len(prof) == 1
    assert prof[0]["risk_level"] == "conservative"


def test_submit_全选C_进取型(risk_service, auth_user_id):
    q = risk_service.get_active_questionnaire()
    r = risk_service.submit_answers(auth_user_id, q["id"], _answers("C"))
    assert r["success"] is True
    assert r["profile"]["risk_level"] == "aggressive"


def test_get_latest_profile_提交后可查(risk_service, auth_user_id):
    q = risk_service.get_active_questionnaire()
    risk_service.submit_answers(auth_user_id, q["id"], _answers("B"))
    prof = risk_service.get_latest_profile(auth_user_id)
    assert prof is not None
    assert prof["risk_level"] == "moderate"


def test_重复提交是更新不是新增(risk_service, supabase_client, auth_user_id):
    q = risk_service.get_active_questionnaire()
    risk_service.submit_answers(auth_user_id, q["id"], _answers("A"))
    risk_service.submit_answers(auth_user_id, q["id"], _answers("C"))

    # 答案表和画像表都只保留 1 条（upsert 覆盖，非 append）
    ans = supabase_client.table("user_risk_answers").select("*").eq("user_id", auth_user_id).execute().data
    assert len(ans) == 1
    prof = supabase_client.table("user_risk_profiles").select("*").eq("user_id", auth_user_id).execute().data
    assert len(prof) == 1
    # 最终画像被第二次提交覆盖为进取型
    assert prof[0]["risk_level"] == "aggressive"
