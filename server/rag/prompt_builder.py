from typing import List, Dict


def build_prompt(question: str, decision: Dict, chunks: List[Dict]) -> str:
    lines = []
    lines.append("# Decision:\n")
    lines.append(f"Intent: {decision.get('intent')}\n")
    lines.append(f"Output format: {decision.get('output_format')}\n")
    lines.append("\n# Context:\n")
    for i, c in enumerate(chunks):
        lines.append(f"--- Chunk {i+1} (score={c.get('score'):.4f}) ---\n")
        lines.append(c.get("text") + "\n\n")
    lines.append("# Question:\n")
    lines.append(question + "\n")
    lines.append("\n# Instructions:\n")
    if decision.get("intent") == "comparison":
        lines.append("Please produce a concise comparison table where relevant.\n")
    elif decision.get("intent") == "summary":
        lines.append("Please summarize the key points using bullets.\n")
    else:
        lines.append("Answer based on the provided context. If insufficient, say you don't know.\n")

    return "\n".join(lines)
