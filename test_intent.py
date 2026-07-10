"""
意图识别评测脚本
评测 QuestionAgent 对 20 条测试消息的意图分类准确率
验收标准：准确率 ≥ 18/20 (90%)
"""
import json
import sys
import types
from pathlib import Path

# 确保能导入 server 包
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- 绕过 server/__init__.py 对 fastapi 的依赖 ---
# 1. 创建空的 server 包，阻止 __init__.py 执行
server_pkg = types.ModuleType("server")
server_pkg.__path__ = [str(PROJECT_ROOT / "server")]
server_pkg.__package__ = "server"
sys.modules["server"] = server_pkg

# 2. 创建 server.models 子包
server_models = types.ModuleType("server.models")
server_models.__path__ = [str(PROJECT_ROOT / "server" / "models")]
server_models.__package__ = "server.models"
sys.modules["server.models"] = server_models

# 3. 加载 DecisionResult
import importlib
_decision_spec = importlib.util.spec_from_file_location(
    "server.models.decision",
    PROJECT_ROOT / "server" / "models" / "decision.py",
)
_decision_mod = importlib.util.module_from_spec(_decision_spec)
sys.modules["server.models.decision"] = _decision_mod
_decision_spec.loader.exec_module(_decision_mod)

# 4. 加载 QuestionAgent
_qa_spec = importlib.util.spec_from_file_location(
    "server.agents.question_agent",
    PROJECT_ROOT / "server" / "agents" / "question_agent.py",
)
_qa_mod = importlib.util.module_from_spec(_qa_spec)
sys.modules["server.agents.question_agent"] = _qa_mod
_qa_spec.loader.exec_module(_qa_mod)
QuestionAgent = _qa_mod.QuestionAgent


def load_test_cases(path: str = "intent_test_cases.json") -> list:
    """加载测试用例"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate(agent: QuestionAgent, cases: list) -> tuple[int, list[dict]]:
    """
    逐条评测意图识别准确率
    返回：(正确数, 详细结果列表)
    """
    correct = 0
    results = []

    for case in cases:
        question = case["question"]
        expected = case["expected_intent"]

        decision = agent.analyze(question)
        predicted = decision.intent
        is_correct = predicted == expected

        if is_correct:
            correct += 1

        results.append({
            "id": case["id"],
            "question": question,
            "expected": expected,
            "predicted": predicted,
            "correct": is_correct,
        })

    return correct, results


def print_report(correct: int, total: int, results: list[dict]):
    """打印评测报告"""
    accuracy = correct / total * 100

    print("=" * 60)
    print("意图识别评测报告")
    print("=" * 60)
    print(f"总用例数: {total}")
    print(f"正确数:   {correct}")
    print(f"准确率:   {accuracy:.1f}% ({correct}/{total})")
    print(f"验收标准: ≥ 90% (18/20)")
    print(f"结果:     {'✅ 通过' if correct >= 18 else '❌ 未通过'}")
    print("=" * 60)

    # 详细结果
    print("\n详细结果:")
    print("-" * 60)
    for r in results:
        mark = "✅" if r["correct"] else "❌"
        print(f"  {mark} [{r['id']:02d}] {r['question']}")
        if not r["correct"]:
            print(f"         期望: {r['expected']}  |  实际: {r['predicted']}")

    # 错误用例汇总
    errors = [r for r in results if not r["correct"]]
    if errors:
        print(f"\n错误用例 ({len(errors)} 条):")
        for r in errors:
            print(f"  [{r['id']:02d}] 期望={r['expected']}  实际={r['predicted']}  问题: {r['question']}")

    print()


def main():
    agent = QuestionAgent()
    cases = load_test_cases()

    correct, results = evaluate(agent, cases)
    print_report(correct, len(cases), results)

    # 返回退出码：通过=0，未通过=1
    sys.exit(0 if correct >= 18 else 1)


if __name__ == "__main__":
    main()
