"""
统一 LLM 服务测试

测试 server/llm.py 中的 LLM 单例和工具绑定。

测试覆盖：
- get_llm() 单例模式（多次调用返回同一实例）
- get_llm_with_tools() 返回绑定了工具的实例
- 配置参数正确传递

注意：这些测试 mock 了 ChatAnthropic 构造函数，不会真正调用 API。
"""
from unittest.mock import patch, MagicMock
import pytest


class TestGetLlm:
    """LLM 单例测试"""

    def setup_method(self):
        """每个测试前重置单例，避免测试间干扰"""
        import server.llm
        server.llm._llm_instance = None

    def test_singleton_returns_same_instance(self, ):
        """多次调用 get_llm() 应返回同一个实例"""
        with patch("server.llm.ChatAnthropic") as mock_cls:
            # 模拟 ChatAnthropic 构造函数返回一个 mock 实例
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            from server.llm import get_llm

            llm1 = get_llm()
            llm2 = get_llm()

            # 应该是同一个对象
            assert llm1 is llm2, "get_llm() 应返回同一实例（单例模式）"
            # ChatAnthropic 构造函数只应被调用一次
            assert mock_cls.call_count == 1, f"ChatAnthropic 应只构造一次，实际调用: {mock_cls.call_count}"
            print(f"[DEBUG] get_llm() 调用 2 次，ChatAnthropic 构造次数: {mock_cls.call_count}")

    def test_singleton_uses_settings_config(self):
        """get_llm() 应使用 SETTINGS 中的配置"""
        with patch("server.llm.ChatAnthropic") as mock_cls:
            mock_cls.return_value = MagicMock()

            from server.llm import get_llm
            from server.config.settings import SETTINGS

            get_llm()

            # 检查构造函数参数
            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs["model"] == SETTINGS.LYRA_MODEL, (
                f"model 应为 {SETTINGS.LYRA_MODEL}，实际: {call_kwargs.kwargs.get('model')}"
            )
            assert call_kwargs.kwargs["max_tokens"] == SETTINGS.LYRA_MAX_TOKENS, (
                f"max_tokens 应为 {SETTINGS.LYRA_MAX_TOKENS}，实际: {call_kwargs.kwargs.get('max_tokens')}"
            )
            print(f"[DEBUG] ChatAnthropic 构造参数: model={call_kwargs.kwargs['model']}, "
                  f"max_tokens={call_kwargs.kwargs['max_tokens']}")


class TestGetLlmWithTools:
    """工具绑定测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        import server.llm
        server.llm._llm_instance = None

    def test_bind_tools_calls_bind_tools(self):
        """get_llm_with_tools() 应调用 base_llm.bind_tools(tools)"""
        with patch("server.llm.ChatAnthropic") as mock_cls:
            mock_base = MagicMock()
            mock_bound = MagicMock()
            mock_base.bind_tools.return_value = mock_bound
            mock_cls.return_value = mock_base

            from server.llm import get_llm_with_tools

            # 传入模拟的 tools 列表
            mock_tools = [MagicMock(), MagicMock()]
            result = get_llm_with_tools(mock_tools)

            # bind_tools 应该被调用，并传入 tools 列表
            mock_base.bind_tools.assert_called_once_with(mock_tools)
            assert result is mock_bound, "应返回 bind_tools 后的实例"
            print(f"[DEBUG] get_llm_with_tools() 调用 bind_tools，传入 {len(mock_tools)} 个工具")

    def test_bind_tools_not_cached(self):
        """get_llm_with_tools() 每次都应返回新的绑定实例（不缓存）"""
        with patch("server.llm.ChatAnthropic") as mock_cls:
            mock_base = MagicMock()
            mock_cls.return_value = mock_base

            from server.llm import get_llm_with_tools

            tools1 = [MagicMock()]
            tools2 = [MagicMock(), MagicMock()]

            get_llm_with_tools(tools1)
            get_llm_with_tools(tools2)

            # bind_tools 应被调用两次（不缓存）
            assert mock_base.bind_tools.call_count == 2, (
                f"bind_tools 应调用 2 次，实际: {mock_base.bind_tools.call_count}"
            )
            print(f"[DEBUG] get_llm_with_tools() 调用 2 次，bind_tools 调用次数: {mock_base.bind_tools.call_count}")
