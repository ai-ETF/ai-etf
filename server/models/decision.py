from dataclasses import dataclass
from typing import Optional


@dataclass
class DecisionResult:
    intent: str
    output_format: str
    top_k: int
    doc_filter: Optional[str] = None
