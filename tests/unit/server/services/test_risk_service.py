"""risk_service 单元测试：风险提示文案与画像计算。

模块名称：server/services/risk_service.py
所测功能：_build_warning_message（提示文案）、_validate_answers（答案校验）、
         _calculate_score（加权总分）、_determine_risk_level（等级判定）、
         _format_profile_result（画像格式化）
测试方法：被测方法均不访问 self._client，用 RiskService.__new__ 跳过 __init__ 里的
         get_supabase() 调用，全程不联网、不连 Supabase。

阈值口径（THRESHOLD_*）：总分 ≤1.6 → conservative，≤2.4 → moderate，>2.4 → aggressive。
"""
from server.services.risk_service import RiskService, _build_warning_message


def _svc() -> RiskService:
    """构造不连库的 RiskService：跳过 __init__ 里的 get_supabase() 调用。"""
    return RiskService.__new__(RiskService)


# ==================== _build_warning_message：提示文案 ====================


def test_info级别_提示差异_不含配置比例():
    msg = _build_warning_message("info", "保守型", "中等风险", None)
    assert "权益类投资产品" in msg
    assert "中等风险" in msg
    assert "保守型" in msg
    assert "%" not in msg


def test_warning级别_含警示与建议比例():
    msg = _build_warning_message("warning", "保守型", "较高风险", 10)
    assert "⚠️" in msg
    assert "10%" in msg
    assert "较高风险" in msg


def test_alert级别_含强烈警示与建议比例():
    msg = _build_warning_message("alert", "保守型", "高风险", 5)
    assert "🔴" in msg
    assert "5%" in msg
    assert "高风险" in msg


# ==================== _validate_answers：答案校验 ====================

QUESTIONS = [
    {"id": "q1", "options": [{"value": "A"}, {"value": "B"}]},
    {"id": "q2", "options": [{"value": "A"}, {"value": "B"}]},
]


def test_全部合法_通过():
    answers = [
        {"question_id": "q1", "value": "A"},
        {"question_id": "q2", "value": "B"},
    ]
    valid, err = _svc()._validate_answers(QUESTIONS, answers)
    assert valid is True
    assert err is None


def test_答案数量不符_报错():
    answers = [{"question_id": "q1", "value": "A"}]
    valid, err = _svc()._validate_answers(QUESTIONS, answers)
    assert valid is False
    assert err == "请回答全部 2 道题目"


def test_题目不存在_报错():
    answers = [
        {"question_id": "q1", "value": "A"},
        {"question_id": "q9", "value": "A"},
    ]
    valid, err = _svc()._validate_answers(QUESTIONS, answers)
    assert valid is False
    assert err == "题目 q9 不存在"


def test_重复作答_报错():
    answers = [
        {"question_id": "q1", "value": "A"},
        {"question_id": "q1", "value": "B"},
    ]
    valid, err = _svc()._validate_answers(QUESTIONS, answers)
    assert valid is False
    assert err == "题目 q1 重复作答"


def test_选项越界_报错并列出有效选项():
    answers = [
        {"question_id": "q1", "value": "C"},
        {"question_id": "q2", "value": "A"},
    ]
    valid, err = _svc()._validate_answers(QUESTIONS, answers)
    assert valid is False
    assert err == '题目 q1 的选项 "C" 无效，有效选项: A, B'


# ==================== _calculate_score：加权总分 ====================

SCORE_QUESTIONS = [
    {
        "id": "q1",
        "weight": 0.5,
        "options": [{"value": "A", "risk_score": 1}, {"value": "B", "risk_score": 2}],
    },
    {
        "id": "q2",
        "weight": 0.5,
        "options": [{"value": "A", "risk_score": 3}, {"value": "B", "risk_score": 4}],
    },
]


def test_加权总分正常计算():
    answers = [
        {"question_id": "q1", "value": "B"},
        {"question_id": "q2", "value": "B"},
    ]
    result = _svc()._calculate_score(SCORE_QUESTIONS, answers)
    # q1: 2*0.5=1.0, q2: 4*0.5=2.0，总分 (1+2)/(0.5+0.5)=3.0
    assert result["total_score"] == 3.0
    assert len(result["weighted_scores"]) == 2


def test_选项匹配不到_跳过该题():
    answers = [
        {"question_id": "q1", "value": "C"},  # 无匹配选项 → 跳过
        {"question_id": "q2", "value": "B"},
    ]
    result = _svc()._calculate_score(SCORE_QUESTIONS, answers)
    # q1 被跳过，其 weight 不计入；只剩 q2：4*0.5 / 0.5 = 4.0
    assert result["total_score"] == 4.0
    assert [w["question_id"] for w in result["weighted_scores"]] == ["q2"]


def test_权重和为0_返回0():
    qs = [{"id": "q1", "weight": 0, "options": [{"value": "A", "risk_score": 5}]}]
    answers = [{"question_id": "q1", "value": "A"}]
    result = _svc()._calculate_score(qs, answers)
    assert result["total_score"] == 0


def test_加权总分四舍五入到两位小数():
    qs = [
        {"id": "q1", "weight": 1, "options": [{"value": "A", "risk_score": 1}]},
        {"id": "q2", "weight": 1, "options": [{"value": "A", "risk_score": 1}]},
        {"id": "q3", "weight": 1, "options": [{"value": "A", "risk_score": 2}]},
    ]
    answers = [
        {"question_id": "q1", "value": "A"},
        {"question_id": "q2", "value": "A"},
        {"question_id": "q3", "value": "A"},
    ]
    result = _svc()._calculate_score(qs, answers)
    # (1+1+2)/3 = 1.3333... → round 到 1.33
    assert result["total_score"] == 1.33


def test_维度得分_有category用category否则用题目id():
    qs = [
        {
            "id": "q1",
            "category": "风险承受",
            "weight": 0.5,
            "options": [{"value": "A", "risk_score": 2}],
        },
        {
            "id": "q2",
            "weight": 0.5,
            "options": [{"value": "A", "risk_score": 3}],
        },
    ]
    answers = [
        {"question_id": "q1", "value": "A"},
        {"question_id": "q2", "value": "A"},
    ]
    result = _svc()._calculate_score(qs, answers)
    assert result["dimension_scores"] == {"风险承受": 2, "q2": 3}


# ==================== _determine_risk_level：等级判定 ====================


def test_总分恰好1_6_为conservative():
    assert _svc()._determine_risk_level(1.6) == "conservative"


def test_总分低于1_6_为conservative():
    assert _svc()._determine_risk_level(1.0) == "conservative"


def test_总分越过1_6_为moderate():
    assert _svc()._determine_risk_level(1.61) == "moderate"


def test_总分恰好2_4_为moderate():
    assert _svc()._determine_risk_level(2.4) == "moderate"


def test_总分越过2_4_为aggressive():
    assert _svc()._determine_risk_level(2.41) == "aggressive"


# ==================== _format_profile_result：画像格式化 ====================


def test_正常画像_字段齐全():
    profile = {
        "risk_level": "moderate",
        "risk_label": "稳健型",
        "total_score": 2.0,
        "dimension_scores": {"风险承受": 2},
        "ai_summary": "稳健型摘要",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    result = _svc()._format_profile_result(profile)
    assert result["risk_level"] == "moderate"
    assert result["risk_label"] == "稳健型"
    assert result["total_score"] == 2.0
    assert result["dimension_scores"] == {"风险承受": 2}
    assert result["summary"] == "稳健型摘要"
    assert result["created_at"] == "2026-01-01T00:00:00+00:00"


def test_维度得分为JSON字符串_自动解析():
    profile = {"dimension_scores": '{"风险承受": 2}', "total_score": 2.0}
    result = _svc()._format_profile_result(profile)
    assert result["dimension_scores"] == {"风险承受": 2}


def test_维度得分为非法JSON_回退空字典():
    profile = {"dimension_scores": "not-json", "total_score": 2.0}
    result = _svc()._format_profile_result(profile)
    assert result["dimension_scores"] == {}


def test_字段缺失_回退默认值():
    result = _svc()._format_profile_result({})
    assert result["risk_level"] == ""
    assert result["risk_label"] == ""
    assert result["total_score"] == 0.0
    assert result["dimension_scores"] == {}
    assert result["summary"] == ""
    assert result["created_at"] == ""
