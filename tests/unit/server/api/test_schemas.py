"""schemas 单元测试：Pydantic 请求/响应模型校验。

模块名称：server/models/schemas.py
所测功能：必填字段、类型转换、可选字段默认值、嵌套模型校验
测试方法：直接实例化模型，纯内存校验，不联网、不连 Supabase。
"""
import pytest
from pydantic import ValidationError

from server.models.schemas import (
    AutoInvestConfigRequest,
    PurchaseRequest,
    SubmitAnswerItem,
    SubmitRequest,
    WatchlistAddRequest,
)


def test_PurchaseRequest_必填字段缺失_抛错():
    with pytest.raises(ValidationError):
        PurchaseRequest()
    with pytest.raises(ValidationError):
        PurchaseRequest(fund_code="110020")  # 缺 amount


def test_PurchaseRequest_int自动转float():
    req = PurchaseRequest(fund_code="110020", amount=100)
    assert req.amount == 100.0
    assert isinstance(req.amount, float)


def test_WatchlistAddRequest_fund_name可选默认None():
    req = WatchlistAddRequest(fund_code="512890")
    assert req.fund_name is None


def test_WatchlistAddRequest_缺fund_code抛错():
    with pytest.raises(ValidationError):
        WatchlistAddRequest()


def test_SubmitRequest_缺answers抛错():
    with pytest.raises(ValidationError):
        SubmitRequest(questionnaire_id="q1")


def test_SubmitAnswerItem_缺value抛错():
    with pytest.raises(ValidationError):
        SubmitAnswerItem(question_id="q1")


def test_AutoInvestConfigRequest_reserve可选默认0():
    req = AutoInvestConfigRequest(enabled=True)
    assert req.reserve == 0.0


def test_AutoInvestConfigRequest_缺enabled抛错():
    with pytest.raises(ValidationError):
        AutoInvestConfigRequest()
