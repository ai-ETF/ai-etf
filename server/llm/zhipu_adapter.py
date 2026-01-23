from typing import Dict, List, Any, Union, Optional, Generator
from langchain_core.language_models import BaseLanguageModel
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.outputs import Generation, LLMResult
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

try:
    from zhipuai import ZhipuAI
    ZHIPU_AVAILABLE = True
except ImportError:
    ZHIPU_AVAILABLE = False
    if not logging.getLogger(__name__).handlers:
        logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).warning("zhipuai module not installed. Install it with 'pip install zhipuai'")


class ZhipuLLM(BaseLanguageModel):
    """
    智谱AI LLM 适配器，用于与LangChain集成
    支持在zhipuai未安装时优雅降级
    """
    client: Optional['ZhipuAI'] = None
    api_key: str = Field(default="")
    model: str = Field(default="glm-4")
    
    class Config:
        arbitrary_types_allowed = True

    def __init__(self, api_key: str = "", model: str = "glm-4", **kwargs):
        super().__init__(**kwargs)
        
        if not ZHIPU_AVAILABLE:
            logger.warning("zhipuai not available, initializing with dummy client")
            self.client = None
        else:
            self.client = ZhipuAI(api_key=api_key)
        
        self.api_key = api_key
        self.model = model

    @property
    def _llm_type(self) -> str:
        return "zhipu"

    def _call(
        self,
        prompt: str,
        stop: List[str] = None,
        run_manager: CallbackManagerForLLMRun = None,
        **kwargs: Any,
    ) -> str:
        """
        执行同步调用
        """
        if not ZHIPU_AVAILABLE or not self.api_key:
            logger.warning("zhipuai not available or API key not provided, returning mock response")
            return f"模拟响应: {prompt[:50]}..."
        
        try:
            logger.debug(f"调用智谱AI API，模型: {self.model}")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                **kwargs  # 传递额外参数
            )
            
            content = response.choices[0].message.content
            logger.debug(f"智谱AI响应成功，内容长度: {len(content)}")
            return content
            
        except Exception as e:
            logger.error(f"调用智谱AI API时发生错误: {str(e)}")
            return f"错误: {str(e)}"

    def generate(
        self,
        prompts: List[str],
        stop: Optional[List[str]] = None,
        callbacks=None,
        **kwargs: Any
    ) -> LLMResult:
        """
        批量生成响应
        """
        generations = []
        for prompt in prompts:
            text = self._call(prompt, stop=stop, **kwargs)
            generations.append([Generation(text=text)])
        
        return LLMResult(generations=generations)

    async def agenerate(
        self,
        prompts: List[str],
        stop: List[str] = None,
        callbacks=None,
        **kwargs: Any
    ) -> LLMResult:
        """
        异步批量生成响应
        """
        # 对于同步API，直接调用同步方法
        return self.generate(prompts, stop=stop, callbacks=callbacks, **kwargs)

    def predict(
        self,
        text: str,
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> str:
        """
        预测方法
        """
        return self._call(text, stop=stop, **kwargs)

    async def apredict(
        self,
        text: str,
        *,
        stop: List[str] = None,
        **kwargs: Any
    ) -> str:
        """
        异步预测方法
        """
        return self.predict(text, stop=stop, **kwargs)

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """
        识别参数
        """
        return {"model": self.model, "available": ZHIPU_AVAILABLE}

    def generate_prompt(
        self,
        prompts: List[Any],
        stop: List[str] = None,
        callbacks=None,
        **kwargs: Any
    ) -> LLMResult:
        """
        生成提示的响应
        """
        if isinstance(prompts[0], str):
            prompt_strings = prompts
        else:
            prompt_strings = [p.to_string() if hasattr(p, 'to_string') else str(p) for p in prompts]
        return self.generate(prompt_strings, stop=stop, callbacks=callbacks, **kwargs)

    def predict_messages(
        self,
        messages: List[BaseMessage],
        stop: List[str] = None,
        **kwargs: Any
    ) -> BaseMessage:
        """
        预测消息
        """
        if not messages:
            prompt = ""
        else:
            prompt = messages[0].content if hasattr(messages[0], 'content') else str(messages[0])
        result = self._call(prompt, stop=stop, **kwargs)
        return HumanMessage(content=result)

    def invoke(self, input: Union[str, Dict], config=None, **kwargs) -> str:
        """
        调用模型
        """
        if isinstance(input, str):
            prompt = input
        elif isinstance(input, dict) and 'input' in input:
            prompt = input['input']
        else:
            prompt = str(input)
            
        return self._call(prompt, **kwargs)
        
    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        """
        流式生成响应
        """
        if not ZHIPU_AVAILABLE or not self.api_key:
            logger.warning("zhipuai not available or API key not provided, returning mock stream response")
            # 模拟流式响应
            response = f"模拟流式响应: {prompt[:50]}..."
            for char in response:
                yield char
            return
        
        try:
            logger.debug(f"调用智谱AI流式API，模型: {self.model}")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                stream=True  # 启用流式响应
            )
            
            # 流式处理响应
            for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
                    
        except Exception as e:
            logger.error(f"调用智谱AI流式API时发生错误: {str(e)}")
            # 发生错误时返回错误信息
            error_msg = f"流式响应错误: {str(e)}"
            for char in error_msg:
                yield char