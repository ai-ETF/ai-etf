"""
情绪检测模块测试

测试 server.graphs.lyra.prompts.detect_emotion() 函数。
该函数基于关键词匹配检测用户输入中的情绪信号。

测试覆盖：
- 单一情绪检测（fomo, anxiety, regret, overconfidence）
- 多情绪同时检测
- 无情绪信号的输入
- 边界情况（空字符串、部分匹配）
"""
from server.graphs.lyra.prompts import detect_emotion


class TestDetectEmotion:
    """情绪检测函数测试集"""

    # ========== FOMO（害怕错过）==========

    def test_detect_fomo_踏空(self):
        """输入包含"踏空"应检测到 fomo"""
        result = detect_emotion("我踏空了，一直涨没买")
        assert "fomo" in result, f"应检测到 fomo，实际: {result}"
        print(f"[DEBUG] 输入='我踏空了' → 检测结果: {result}")

    def test_detect_fomo_错过(self):
        """输入包含"错过"应检测到 fomo"""
        result = detect_emotion("这次机会错过了好可惜")
        assert "fomo" in result
        print(f"[DEBUG] 输入='错过机会' → 检测结果: {result}")

    def test_detect_fomo_早知道该买(self):
        """输入包含"早知道该买"应检测到 fomo"""
        result = detect_emotion("早知道该买消费50了")
        assert "fomo" in result
        print(f"[DEBUG] 输入='早知道该买' → 检测结果: {result}")

    # ========== 焦虑（Anxiety）==========

    def test_detect_anxiety_跌了怎么办(self):
        """输入包含"跌了怎么办"应检测到 anxiety"""
        result = detect_emotion("沪深300跌了怎么办，要不要卖")
        assert "anxiety" in result, f"应检测到 anxiety，实际: {result}"
        print(f"[DEBUG] 输入='跌了怎么办' → 检测结果: {result}")

    def test_detect_anxiety_要不要卖(self):
        """输入包含"要不要卖"应检测到 anxiety"""
        result = detect_emotion("我现在要不要卖")
        assert "anxiety" in result
        print(f"[DEBUG] 输入='要不要卖' → 检测结果: {result}")

    # ========== 后悔（Regret）==========

    def test_detect_regret_后悔(self):
        """输入包含"后悔"应检测到 regret"""
        result = detect_emotion("好后悔之前没买")
        assert "regret" in result
        print(f"[DEBUG] 输入='后悔' → 检测结果: {result}")

    def test_detect_regret_拍大腿(self):
        """输入包含"拍大腿"应检测到 regret"""
        result = detect_emotion("拍大腿，卖早了")
        assert "regret" in result
        print(f"[DEBUG] 输入='拍大腿' → 检测结果: {result}")

    # ========== 盲目自信（Overconfidence）==========

    def test_detect_overconfidence_肯定涨(self):
        """输入包含"肯定涨"应检测到 overconfidence"""
        result = detect_emotion("这次肯定涨，稳赚")
        assert "overconfidence" in result
        print(f"[DEBUG] 输入='肯定涨' → 检测结果: {result}")

    def test_detect_overconfidence_必涨(self):
        """输入包含"必涨"应检测到 overconfidence"""
        result = detect_emotion("半导体必涨，百分百")
        assert "overconfidence" in result
        print(f"[DEBUG] 输入='必涨' → 检测结果: {result}")

    # ========== 多情绪同时检测 ==========

    def test_detect_multiple_emotions(self):
        """输入同时包含多个情绪关键词时，应检测到多个情绪"""
        result = detect_emotion("早知道该买，现在踏空了好后悔")
        # 包含 "早知道" (regret/fomo), "踏空" (fomo), "后悔" (regret)
        assert len(result) >= 2, f"应检测到多个情绪，实际: {result}"
        assert "fomo" in result, f"应包含 fomo，实际: {result}"
        assert "regret" in result, f"应包含 regret，实际: {result}"
        print(f"[DEBUG] 多情绪输入 → 检测结果: {result}")

    # ========== 无情绪信号 ==========

    def test_no_emotion_normal_input(self):
        """普通投资咨询不应触发情绪检测"""
        result = detect_emotion("沪深300和中证500哪个好")
        assert result == [], f"普通输入不应触发情绪，实际: {result}"
        print(f"[DEBUG] 普通输入 → 检测结果: {result}")

    def test_no_emotion_empty_string(self):
        """空字符串不应触发情绪检测"""
        result = detect_emotion("")
        assert result == [], f"空输入不应触发情绪，实际: {result}"
        print(f"[DEBUG] 空输入 → 检测结果: {result}")

    def test_no_emotion_partial_match(self):
        """部分匹配不应触发（如"后悔"的子串"后"）"""
        result = detect_emotion("后面怎么走")
        assert result == [], f"部分匹配不应触发情绪，实际: {result}"
        print(f"[DEBUG] 部分匹配输入 → 检测结果: {result}")
