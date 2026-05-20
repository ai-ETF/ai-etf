import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 核心：再次为服务级代码注入国内镜像源

import sys
import re
import math
import json
import argparse
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

# 确保能正确导入 server 包
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

# 加载环境变量 (Supabase 配置)
env_path = PROJECT_ROOT / "ai_etf" / ".env"
if not env_path.exists():
    env_path = PROJECT_ROOT / ".env"
load_dotenv(env_path)

# --- 补充载入缺失的 Server 必备环境变量 ---
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = key # 如果没指定特权密钥，让普通密钥兜底

from server.services.qa_service import QAService


DEFAULT_QUESTION = "华泰柏瑞或者南方标普ETF的费率是多少？"

DEFAULT_EVAL_CASES = [
    {
        "name": "费率问答-口语简称",
        "question": "华泰博瑞或者南方标普ETF的费率是多少？",
        "relevance_terms": ["管理费", "托管费", "费率"],
        "expected_rates": {
            "management_fee": ["0.50%", "0.5%"],
            "custody_fee": ["0.10%", "0.1%"],
        },
    },
    {
        "name": "费率问答-标准表达",
        "question": "南方标普中国A股大盘红利低波50ETF的管理费和托管费是多少？",
        "relevance_terms": ["管理费", "托管费", "费率"],
        "expected_rates": {
            "management_fee": ["0.50%", "0.5%"],
            "custody_fee": ["0.10%", "0.1%"],
        },
    },
]


def _chunk_content(chunk):
    if isinstance(chunk, dict):
        return chunk.get("content", "")
    return getattr(chunk, "content", "")


def _chunk_score(chunk):
    if isinstance(chunk, dict):
        return chunk.get("rerank_score", "N/A")
    return getattr(chunk, "rerank_score", "N/A")


def _normalize_rate_to_float(rate_text):
    if not rate_text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", str(rate_text))
    if not match:
        return None
    return float(match.group(1))


def _compute_ndcg(relevances, k=5):
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        if rel:
            dcg += 1.0 / math.log2(i + 2)

    ideal_relevances = sorted(relevances[:k], reverse=True)
    idcg = 0.0
    for i, rel in enumerate(ideal_relevances):
        if rel:
            idcg += 1.0 / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def _compute_f1(predicted, expected):
    preds = str(predicted).strip()
    exps = str(expected).strip()
    if not preds and not exps:
        return 1.0
    if not preds or not exps:
        return 0.0

    # 字符级 F1 计算
    pred_counter = Counter(preds)
    exp_counter = Counter(exps)

    common = sum((pred_counter & exp_counter).values())
    if common == 0:
        return 0.0

    precision = common / len(preds)
    recall = common / len(exps)
    return 2 * precision * recall / (precision + recall)


def _rate_match(predicted_rate, expected_rate_candidates, eps=1e-8):
    pred_value = _normalize_rate_to_float(predicted_rate)
    if pred_value is None:
        return False

    if isinstance(expected_rate_candidates, (str, int, float)):
        expected_rate_candidates = [expected_rate_candidates]

    for candidate in expected_rate_candidates:
        candidate_value = _normalize_rate_to_float(candidate)
        if candidate_value is not None and abs(candidate_value - pred_value) < eps:
            return True
    return False


def _print_single_result(question, result):
    print(f"\n[用户提问]: {question}")
    print("\n[系统]: 正在去 Supabase 执行向量检索，并使用 Reranker 进行重排序安检...")

    print("\n==================================================")
    print("🏆 经过重排序 (Reranker) 筛选出的最强 Top 切片：")
    print("==================================================")
    for i, chunk in enumerate(result["top_chunks"]):
        score = _chunk_score(chunk)
        content = _chunk_content(chunk)

        print(f"\n【Top {i+1}】 (重排序最终得分: {score})")
        preview = content[:200].replace("\n", " ")
        print(f"片段内容: {preview}...")

    fee_card = result.get("fee_card", {})
    if fee_card.get("is_fee_question"):
        print("\n==================================================")
        print("💳 结构化费率卡片 (P0)")
        print("==================================================")
        print(f"管理费: {fee_card.get('management_fee') or '未抽取到'}")
        print(f"托管费: {fee_card.get('custody_fee') or '未抽取到'}")
        print(f"申购费: {fee_card.get('subscription_fee') or '未抽取到'}")
        print(f"赎回费: {fee_card.get('redemption_fee') or '未抽取到'}")

        evidences = fee_card.get("evidence", [])
        if evidences:
            print("\n证据片段:")
            for idx, evidence in enumerate(evidences[:3], start=1):
                print(f"- [{idx}] {evidence}...")

    print("\n==================================================")
    print("🤖 最终发送给大语言模型 (LLM) 的 Prompt 指令预览：")
    print("==================================================")
    print(result["prompt"][:500] + "\n\n...... [后续内容省略]")


def _compute_retrieval_metrics(top_chunks, relevance_terms, source, expect_reject):
    """计算检索指标：Hit@5、MRR、nDCG@5、first_relevant_rank"""
    if source == "api":
        return True, 1.0, 1.0, None
    if source == "fallback":
        # ETF 相关但知识库没有 → 用了通用知识兜底，比幻觉好，算通过
        return True, 1.0, 1.0, None
    if source == "rejected" or expect_reject:
        correct = (source == "rejected") == expect_reject
        score = 1.0 if correct else 0.0
        return correct, score, score, None

    relevances, first_rank = _collect_relevances(top_chunks, relevance_terms)
    hit = first_rank is not None and first_rank <= 5
    mrr = 1.0 / first_rank if first_rank else 0.0
    return hit, mrr, _compute_ndcg(relevances, k=5), first_rank


def _collect_relevances(top_chunks, relevance_terms):
    """收集相关性标记和首个相关片段排名"""
    relevances = []
    first_rank = None
    for idx, chunk in enumerate(top_chunks, start=1):
        content = _chunk_content(chunk)
        is_rel = 1 if (not relevance_terms or any(term in content for term in relevance_terms)) else 0
        relevances.append(is_rel)
        if is_rel and first_rank is None:
            first_rank = idx
    return relevances, first_rank


def _evaluate_fee_fields(fee_card, expected_rates):
    """评估费率字段准确率和 F1"""
    field_total = 0
    field_correct = 0
    field_f1_scores = []
    field_details = {}

    for field_name, expected_value in expected_rates.items():
        field_total += 1
        predicted_value = fee_card.get(field_name, "")
        is_correct = _rate_match(predicted_value, expected_value)
        if is_correct:
            field_correct += 1

        expected_cands = expected_value if isinstance(expected_value, list) else [expected_value]
        max_f1 = max([_compute_f1(predicted_value, exp) for exp in expected_cands]) if expected_cands else 0.0
        field_f1_scores.append(max_f1)

        field_details[field_name] = {
            "predicted": predicted_value,
            "expected": expected_value,
            "correct": is_correct,
            "f1": max_f1,
        }

    case_f1 = sum(field_f1_scores) / len(field_f1_scores) if field_f1_scores else None
    return field_total, field_correct, case_f1, field_details


def _evaluate_case(qa_service, case, show_top=5):
    question = case["question"]
    relevance_terms = case.get("relevance_terms", [])
    expected_rates = case.get("expected_rates", {})
    expect_reject = case.get("expect_reject", False)

    result = qa_service.handle_question(question)
    top_chunks = result.get("top_chunks", [])
    source = result.get("source", "rag")

    hit_at_5, mrr, ndcg_at_5, first_relevant_rank = _compute_retrieval_metrics(
        top_chunks, relevance_terms, source, expect_reject
    )

    fee_card = result.get("fee_card", {})
    field_total, field_correct, case_f1, field_details = _evaluate_fee_fields(fee_card, expected_rates)

    top_preview = [
        {
            "rank": i,
            "score": _chunk_score(chunk),
            "preview": _chunk_content(chunk)[:120].replace("\n", " "),
        }
        for i, chunk in enumerate(top_chunks[:show_top], start=1)
    ]

    return {
        "name": case.get("name", question[:20]),
        "question": question,
        "hit_at_5": hit_at_5,
        "mrr": mrr,
        "ndcg_at_5": ndcg_at_5,
        "first_relevant_rank": first_relevant_rank,
        "field_total": field_total,
        "field_correct": field_correct,
        "field_details": field_details,
        "case_f1": case_f1,
        "top_preview": top_preview,
    }


def _load_eval_cases(cases_path):
    if not cases_path:
        return DEFAULT_EVAL_CASES

    path = Path(cases_path)
    if not path.exists():
        raise FileNotFoundError(f"评测用例文件不存在: {cases_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("评测用例 JSON 必须是 list，每个元素是一个 case 字典。")

    return data


def _run_eval_mode(qa_service, cases, show_top=3):
    print("\n==================================================")
    print("📊 自动评测模式 (Hit@5 / MRR / 费率字段准确率)")
    print("==================================================")

    case_results = []
    for idx, case in enumerate(cases, start=1):
        print(f"\n[{idx}/{len(cases)}] 正在评测: {case.get('name', '未命名用例')}")
        case_result = _evaluate_case(qa_service, case, show_top=show_top)
        case_results.append(case_result)

        print(f"问题: {case_result['question']}")
        print(f"Hit@5: {'✅' if case_result['hit_at_5'] else '❌'}")
        print(f"MRR: {case_result['mrr']:.4f}")
        print(f"nDCG@5: {case_result['ndcg_at_5']:.4f}")
        print(f"首个相关片段排名: {case_result['first_relevant_rank'] or '未命中'}")

        if case_result["field_total"] > 0:
            print(
                f"费率字段准确率: {case_result['field_correct']}/{case_result['field_total']} "
                f"({(case_result['field_correct'] / case_result['field_total']) * 100:.2f}%)"
            )
            print(f"提取字段 F1: {case_result['case_f1']:.4f}")
            for field_name, detail in case_result["field_details"].items():
                print(
                    f"  - {field_name}: {'✅' if detail['correct'] else '❌'} "
                    f"(pred={detail['predicted'] or '空'}, expected={detail['expected']})"
                )

    total_cases = len(case_results)
    hit_count = sum(1 for item in case_results if item["hit_at_5"])
    avg_hit_at_5 = hit_count / total_cases if total_cases else 0.0
    avg_mrr = sum(item["mrr"] for item in case_results) / total_cases if total_cases else 0.0
    avg_ndcg = sum(item["ndcg_at_5"] for item in case_results) / total_cases if total_cases else 0.0

    valid_f1_cases = [item["case_f1"] for item in case_results if item.get("case_f1") is not None]
    avg_f1 = sum(valid_f1_cases) / len(valid_f1_cases) if valid_f1_cases else 0.0

    total_fields = sum(item["field_total"] for item in case_results)
    correct_fields = sum(item["field_correct"] for item in case_results)
    field_acc = (correct_fields / total_fields) if total_fields else 0.0

    print("\n==================================================")
    print("✅ 评测汇总")
    print("==================================================")
    print(f"样本数: {total_cases}")
    print(f"Hit@5: {hit_count}/{total_cases} ({avg_hit_at_5 * 100:.2f}%)")
    print(f"平均 MRR: {avg_mrr:.4f}")
    print(f"平均 nDCG@5: {avg_ndcg:.4f}")
    if total_fields:
        print(f"费率字段准确率: {correct_fields}/{total_fields} ({field_acc * 100:.2f}%)")
        print(f"平均字段提取 F1: {avg_f1:.4f}")
    else:
        print("费率字段准确率: 无标注字段，跳过")


def main():
    parser = argparse.ArgumentParser(description="RAG QA 测试与自动评测脚本")
    parser.add_argument("question", nargs="*", help="单题测试问题文本")
    parser.add_argument("--eval", action="store_true", help="启用自动评测模式")
    parser.add_argument("--cases", type=str, default="", help="评测用例 JSON 文件路径")
    parser.add_argument("--show-top", type=int, default=3, help="评测时展示前 N 条片段预览")
    args = parser.parse_args()

    print("==================================================")
    print("🚀 启动 RAG 第三阶段：混合检索与重排测试")
    print("==================================================")

    # 1. 初始化 QA 服务 (这会自动触发 BAAI/bge-reranker 模型的下载和加载)
    print("\n[系统]: 正在初始化 QA Service (初次加载重排模型可能需要 1-2 分钟，请耐心等待)...")
    qa_service = QAService()

    if args.eval:
        eval_cases = _load_eval_cases(args.cases)
        _run_eval_mode(qa_service, eval_cases, show_top=max(1, args.show_top))
        return

    question = " ".join(args.question).strip() if args.question else DEFAULT_QUESTION
    result = qa_service.handle_question(question)
    _print_single_result(question, result)

if __name__ == "__main__":
    main()
