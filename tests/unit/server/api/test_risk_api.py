"""risk API 单元测试。

模块名称：server/api/risk.py
所测功能：questionnaire / submit / profile 端点（JWT 依赖替身 + RiskService 替身）
测试方法：FastAPI TestClient + dependency_overrides 注入固定 user_id + monkeypatch 服务，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.deps import get_current_user
from server.api.risk import router


class FakeRiskService:
    questionnaire = {
        "id": "q1", "version": "v1",
        "questions": [
            {"id": "q1", "question": "投资期限", "category": "投资期限",
             "options": [{"text": "短期", "value": "A"}]},
        ],
    }
    submit_result = {"success": True, "message": "提交成功", "profile": None}
    profile = None

    def get_active_questionnaire(self):
        return self.questionnaire

    def submit_answers(self, user_id, questionnaire_id, answers):
        return self.submit_result

    def get_latest_profile(self, user_id):
        return self.profile


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("server.api.risk.RiskService", FakeRiskService)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


def test_get_questionnaire(client):
    resp = client.get("/risk/questionnaire")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "q1"
    assert data["total_questions"] == 1


def test_submit_answers(client):
    FakeRiskService.submit_result = {
        "success": True, "message": "提交成功",
        "profile": {
            "risk_level": "moderate", "risk_label": "稳健型", "total_score": 2.0,
            "dimension_scores": {"investment_horizon": 2}, "summary": "稳健型",
        },
    }
    resp = client.post("/risk/submit", json={
        "questionnaire_id": "q1",
        "answers": [{"question_id": "q1", "value": "A"}],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["profile"]["risk_level"] == "moderate"


def test_submit_answers_业务失败返回400(client):
    FakeRiskService.submit_result = {"success": False, "message": "请回答全部 2 道题目"}
    resp = client.post("/risk/submit", json={
        "questionnaire_id": "q1", "answers": [],
    })
    assert resp.status_code == 400


def test_get_profile_有画像(client):
    FakeRiskService.profile = {
        "risk_level": "aggressive", "risk_label": "进取型", "total_score": 2.8,
        "dimension_scores": {"investment_horizon": 3}, "summary": "进取型",
    }
    resp = client.get("/risk/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_profile"] is True
    assert data["profile"]["risk_level"] == "aggressive"


def test_get_profile_无画像(client):
    FakeRiskService.profile = None
    resp = client.get("/risk/profile")
    assert resp.status_code == 200
    assert resp.json()["has_profile"] is False
