"""
条件边路由函数测试

测试 server.graphs.lyra.edges.py 中的路由逻辑。

测试覆盖：
- should_intervene_emotion：情绪干预路由
- route_by_intent：意图路由
- should_end：对话结束判断

这些是纯函数，读取 state dict 返回路由字符串，不需要 mock。
"""
from server.graphs.lyra.edges import (
    should_intervene_emotion,
    route_by_intent,
    should_end,
)


class TestShouldInterveneEmotion:
    """情绪干预路由测试"""

    def test_no_emotion_flags(self):
        """无情绪信号 → 路由到 classify_intent"""
        state = {"emotion_flags": [], "emotion_intervened": False}
        result = should_intervene_emotion(state)
        assert result == "classify_intent", f"无情绪时应路由到 classify_intent，实际: {result}"
        print(f"[DEBUG] emotion_flags=[] → {result}")

    def test_emotion_detected_not_intervened(self):
        """检测到情绪且未干预 → 路由到 emotion_intervention"""
        state = {"emotion_flags": ["fomo"], "emotion_intervened": False}
        result = should_intervene_emotion(state)
        assert result == "emotion_intervention", f"应路由到 emotion_intervention，实际: {result}"
        print(f"[DEBUG] emotion_flags=['fomo'], intervened=False → {result}")

    def test_emotion_already_intervened(self):
        """检测到情绪但已干预 → 路由到 classify_intent（不重复干预）"""
        state = {"emotion_flags": ["fomo"], "emotion_intervened": True}
        result = should_intervene_emotion(state)
        assert result == "classify_intent", f"已干预时应路由到 classify_intent，实际: {result}"
        print(f"[DEBUG] emotion_flags=['fomo'], intervened=True → {result}")

    def test_multiple_emotions_not_intervened(self):
        """多个情绪信号且未干预 → 路由到 emotion_intervention"""
        state = {"emotion_flags": ["fomo", "anxiety"], "emotion_intervened": False}
        result = should_intervene_emotion(state)
        assert result == "emotion_intervention"
        print(f"[DEBUG] emotion_flags=['fomo','anxiety'] → {result}")


class TestRouteByIntent:
    """意图路由测试"""

    def test_buy_decision_high_confidence(self):
        """buy_decision 意图 + 高置信度 → 路由到 buy_decision_skill"""
        state = {"intent": "buy_decision", "intent_confidence": 0.9}
        result = route_by_intent(state)
        assert result == "buy_decision_skill", f"应路由到 buy_decision_skill，实际: {result}"
        print(f"[DEBUG] intent='buy_decision', confidence=0.9 → {result}")

    def test_buy_decision_low_confidence(self):
        """buy_decision 意图但低置信度 → 路由到 output（兜底）"""
        state = {"intent": "buy_decision", "intent_confidence": 0.3}
        result = route_by_intent(state)
        assert result == "output", f"低置信度应路由到 output，实际: {result}"
        print(f"[DEBUG] intent='buy_decision', confidence=0.3 → {result}")

    def test_unknown_intent(self):
        """unknown 意图 → 路由到 output"""
        state = {"intent": "unknown", "intent_confidence": 0.5}
        result = route_by_intent(state)
        assert result == "output", f"unknown 意图应路由到 output，实际: {result}"
        print(f"[DEBUG] intent='unknown' → {result}")

    def test_knowledge_qa_routes_to_output(self):
        """knowledge_qa 意图（暂无 skill）→ 路由到 output"""
        state = {"intent": "knowledge_qa", "intent_confidence": 0.8}
        result = route_by_intent(state)
        assert result == "output", f"knowledge_qa 应路由到 output，实际: {result}"
        print(f"[DEBUG] intent='knowledge_qa' → {result}")

    def test_confidence_exactly_at_threshold(self):
        """置信度恰好等于 0.5 阈值 → 应通过（>= 0.5）"""
        state = {"intent": "buy_decision", "intent_confidence": 0.5}
        result = route_by_intent(state)
        assert result == "buy_decision_skill", f"confidence=0.5 应通过阈值，实际: {result}"
        print(f"[DEBUG] confidence=0.5 (边界值) → {result}")

    def test_confidence_below_threshold(self):
        """置信度略低于阈值 → 路由到 output"""
        state = {"intent": "buy_decision", "intent_confidence": 0.49}
        result = route_by_intent(state)
        assert result == "output", f"confidence=0.49 应被拦截，实际: {result}"
        print(f"[DEBUG] confidence=0.49 (低于阈值) → {result}")

    def test_missing_intent_field(self):
        """state 中缺少 intent 字段 → 应安全降级到 output"""
        state = {"intent_confidence": 0.8}
        result = route_by_intent(state)
        assert result == "output", f"缺少 intent 字段应降级到 output，实际: {result}"
        print(f"[DEBUG] intent 字段缺失 → {result}")


class TestShouldEnd:
    """对话结束判断测试"""

    def test_should_end_true(self):
        """should_end=True → 路由到 end"""
        state = {"should_end": True}
        result = should_end(state)
        assert result == "end", f"should_end=True 应路由到 end，实际: {result}"
        print(f"[DEBUG] should_end=True → {result}")

    def test_should_end_false(self):
        """should_end=False → 路由到 continue（多轮对话）"""
        state = {"should_end": False}
        result = should_end(state)
        assert result == "continue", f"should_end=False 应路由到 continue，实际: {result}"
        print(f"[DEBUG] should_end=False → {result}")

    def test_should_end_missing_field(self):
        """state 中缺少 should_end 字段 → 默认 continue"""
        state = {}
        result = should_end(state)
        assert result == "continue", f"缺少 should_end 字段应默认 continue，实际: {result}"
        print(f"[DEBUG] should_end 字段缺失 → {result}")
