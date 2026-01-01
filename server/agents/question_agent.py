from typing import Optional
from server.models.decision import DecisionResult


class QuestionAgent:
    """Rule-driven agent to classify question intent and output preferences."""

    def analyze(self, question: str, metadata: Optional[dict] = None) -> DecisionResult:
        q = question.lower()
        intent = "general"
        output_format = "text"
        top_k = 5

        if any(k in q for k in ["比较", "对比", "差异"]):
            intent = "comparison"
            top_k = 8
            output_format = "table"
        elif any(k in q for k in ["摘要", "总结", "总结一下"]):
            intent = "summary"
            top_k = 4
            output_format = "text"
        elif any(k in q for k in ["趋势", "趋势性", "未来"]):
            intent = "trend"
            top_k = 6
            output_format = "text"

        return DecisionResult(intent=intent, output_format=output_format, top_k=top_k, doc_filter=None)
