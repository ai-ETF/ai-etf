"""
交互式对话测试

从终端接收用户输入，调用真实 LLM，打印回复。
用于手动验证完整的图流程（意图识别 → 技能路由 → 输出）。

使用方式：
    poetry run python tests/manual_test_chat.py

退出：输入 q 或 quit
"""
import asyncio
import sys
import os

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from server.graphs.lyra.graph import run_lyra

    user_id = "test-user"
    session_id = "manual-test-session"

    print("=" * 50)
    print("莱拉交互测试（真实 LLM）")
    print("输入 q 退出")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input or user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break

        try:
            result = await run_lyra(user_id, session_id, user_input)

            response = result.get("response", "(无回复)")
            intent = result.get("intent", "?")
            confidence = result.get("intent_confidence", 0)
            interrupted = result.get("_interrupted", False)

            print(f"\n莱拉: {response}")
            print(f"  [intent={intent}, confidence={confidence}, interrupted={interrupted}]")

        except Exception as e:
            print(f"\n错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())
