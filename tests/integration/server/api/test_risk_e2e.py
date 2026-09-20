"""P1-5 API 端到端：/api/risk/* 路由 ↔ 服务层 ↔ 真实 Postgres（三表流转）。

模块名称：风险测评 API 路由
所测功能：JWT 鉴权 → 问卷获取 → 答案提交 → 画像查询 的完整纵向切片
使用的测试方法：TestClient + 真实 app + 本地 Supabase + 真实 auth 用户 + 自签 JWT
"""
import pytest

pytestmark = pytest.mark.integration


def _answers(choice: str) -> list:
    return [{"question_id": f"q{i}", "value": choice} for i in range(1, 6)]


def test_问卷获取_返回5道题(api_client, auth_headers, auth_user_id):
    resp = api_client.get("/api/risk/questionnaire", headers=auth_headers(auth_user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "v1.0"
    assert body["total_questions"] == 5
    # 题目不含 weight/risk_score 等内部字段
    assert "risk_score" not in str(body["questions"][0])


def test_提交答案_生成画像_并可查询(api_client, auth_headers, auth_user_id):
    headers = auth_headers(auth_user_id)

    q = api_client.get("/api/risk/questionnaire", headers=headers).json()

    # 提交全选 A（保守型）
    resp = api_client.post(
        "/api/risk/submit",
        json={"questionnaire_id": q["id"], "answers": _answers("A")},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["success"] is True
    assert resp.json()["profile"]["risk_level"] == "conservative"

    # 查询画像
    resp = api_client.get("/api/risk/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["has_profile"] is True
    assert resp.json()["profile"]["risk_level"] == "conservative"


def test_未提交画像_返回无画像(api_client, auth_headers, auth_user_id):
    resp = api_client.get("/api/risk/profile", headers=auth_headers(auth_user_id))
    assert resp.status_code == 200
    assert resp.json()["has_profile"] is False


def test_提交答案数量不符_返回400(api_client, auth_headers, auth_user_id):
    headers = auth_headers(auth_user_id)
    q = api_client.get("/api/risk/questionnaire", headers=headers).json()

    # 只提交 1 道题（问卷要求 5 道）
    resp = api_client.post(
        "/api/risk/submit",
        json={"questionnaire_id": q["id"], "answers": [{"question_id": "q1", "value": "A"}]},
        headers=headers,
    )
    assert resp.status_code == 400
