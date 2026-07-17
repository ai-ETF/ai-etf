from server.agents.question_agent import QuestionAgent
from server.agents.document_agent import DocumentAgent
from server.agents.output_format_agent import OutputFormatAgent
from server.rag.embedder import Embedder
from server.rag.retriever import Retriever
from server.rag.prompt_builder import build_prompt
from server.storage.embedding_repo import EmbeddingRepo
from server.models.decision import DecisionResult
from server.config.settings import SETTINGS
from server.services.finance_api_service import FinanceApiService
import logging
import re

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    pass

logger = logging.getLogger(__name__)


class QAService:
    """
    问答服务类
    负责处理用户问题，包括意图分析、向量检索和提示词构建
    """

    # Reranker 分数低于此阈值判定为"检索内容完全不相关"，直接拒识
    RERANK_THRESHOLD = 0.2

    def __init__(self):
        """
        初始化问答服务
        创建问题分析智能体、嵌入器、检索器和嵌入存储实例
        """
        logger.debug("初始化问答服务")
        self.agent = QuestionAgent()
        self.document_agent = DocumentAgent()
        self.output_format_agent = OutputFormatAgent()
        self.finance_api = FinanceApiService()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        self.emb_repo = EmbeddingRepo()
        self.retriever = Retriever(self.emb_repo)
        
        logger.debug("正在加载 Reranker 重排序模型... (大厂级 RAG 2.0 护城河)")
        try:
            # 引入智源科学院的 BAAI bge-reranker 专门用于中文 RAG 重排
            self.reranker = CrossEncoder('BAAI/bge-reranker-v2-m3')
            logger.debug("Reranker 加载成功！")
        except Exception as e:
            logger.warning(f"Reranker 加载失败，将降级为基础模型检索：{e}")
            self.reranker = None
            
        logger.debug(f"问答服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}")

    def _normalize_question(self, question: str) -> str:
        normalized = question

        # 先做错别字归一化
        normalized = normalized.replace("华泰博瑞", "华泰柏瑞")

        # 再做实体扩展：两段式替换，避免重叠别名发生二次展开
        alias_replacements = [
            ("华泰柏瑞中证红利", "__ALIAS_HTBR_ZZHL__", "华泰柏瑞中证红利低波动交易型开放式指数证券投资基金"),
            ("华泰柏瑞ETF", "__ALIAS_HTBR_ETF__", "华泰柏瑞中证红利低波动交易型开放式指数证券投资基金"),
            ("南方标普ETF", "__ALIAS_NFBP_ETF__", "南方标普中国A股大盘红利低波50交易型开放式指数证券投资基金"),
            ("南方标普", "__ALIAS_NFBP__", "南方标普中国A股大盘红利低波50"),
        ]

        for alias, token, _ in alias_replacements:
            normalized = re.sub(re.escape(alias), token, normalized)
        for _, token, full_name in alias_replacements:
            normalized = normalized.replace(token, full_name)

        if normalized != question:
            logger.debug(f"问题归一化: 原始='{question}' -> 归一化='{normalized}'")

        return normalized

    def _build_retrieval_query(self, normalized_question: str) -> str:
        retrieval_query = normalized_question
        fee_keywords = ("费率", "费用", "管理费", "托管费", "申购费", "赎回费")
        if any(keyword in normalized_question for keyword in fee_keywords):
            retrieval_query = f"{normalized_question} 管理费 托管费 年费率 计提标准"
        return retrieval_query

    def _is_fee_question(self, question: str) -> bool:
        fee_keywords = ("费率", "费用", "管理费", "托管费", "申购费", "赎回费", "年费")
        return any(keyword in question for keyword in fee_keywords)

    # 按类别组织关键词，便于维护和扩展
    _ETF_KEYWORDS = {
        # 1. 基金产品术语
        "product": (
            "etf", "基金", "指数", "qdii", "lof", "联接", "增强",
            "smart", "beta", "货基", "债基", "股基", "混合",
        ),
        # 2. 交易行为
        "action": (
            "申购", "赎回", "定投", "买入", "卖出", "建仓", "加仓",
            "减仓", "抄底", "止盈", "止损", "换仓", "调仓",
        ),
        # 3. 收益与风险指标
        "metric": (
            "净值", "分红", "收益率", "涨跌", "涨幅", "跌幅", "回撤",
            "波动", "夏普", "跟踪误差", "偏离度", "超额",
        ),
        # 4. 账户与持仓
        "account": (
            "持仓", "份额", "封闭", "开放", "仓位", "底仓", "重仓",
            "轻仓", "满仓", "空仓",
        ),
        # 5. 市场与交易所
        "market": (
            "证券", "交易所", "场内", "场外", "二级市场", "一级市场",
        ),
        # 6. 资产类别
        "asset": (
            "股票", "债券", "货币", "黄金", "原油", "商品",
            "比特币", "加密", "虚拟货币", "数字资产",
        ),
        # 7. 指数名称
        "index": (
            "纳斯达克", "标普", "恒生", "科创", "创业板", "沪深",
            "中证", "上证", "深证", "道琼斯", "日经", "富时",
            "msci", "dax",
        ),
        # 8. 行业板块
        "sector": (
            "消费", "医药", "科技", "新能源", "半导体", "芯片",
            "军工", "银行", "券商", "保险", "地产", "白酒",
            "光伏", "锂电", "汽车", "传媒", "游戏", "ai",
        ),
        # 9. 投资目标与策略（暗喻关键词）
        "strategy": (
            "投资", "理财", "炒股", "长线", "短线", "稳健", "保守",
            "激进", "保本", "增值", "跑赢", "通胀", "抗通胀",
            "分散", "配置", "对冲", "套利", "打新", "红利",
            "高股息", "低波", "低波动", "定投", "复利", "长期持有",
        ),
        # 10. 口语化/暗喻表达
        "colloquial": (
            "标的", "品种", "敞口", "上车", "下车", "上车机会",
            "上车吗", "能买吗", "可以买吗", "值得买", "推荐",
            "适合", "怎么选", "选哪个", "哪个好", "比较一下",
        ),
        # 11. 费用相关
        "fee": (
            "费率", "管理费", "托管费", "申购费", "赎回费", "佣金",
            "手续费", "费用", "收费", "怎么收",
        ),
    }

    def _is_etf_related(self, question: str) -> bool:
        """判断问题是否可能与 ETF/基金/投资相关"""
        q = question.lower()
        for category_keywords in self._ETF_KEYWORDS.values():
            if any(kw in q for kw in category_keywords):
                return True
        return False

    def _prefilter_fee_chunks(self, chunks: list) -> list:
        fee_keywords = ("费率", "费用", "管理费", "托管费", "申购费", "赎回费", "年费")
        filtered = []
        for chunk in chunks:
            text_content = chunk.get('content', '') if isinstance(chunk, dict) else getattr(chunk, 'content', '')
            if any(keyword in text_content for keyword in fee_keywords):
                filtered.append(chunk)
        return filtered

    def _build_api_prompt(self, question: str, api_data: dict) -> str:
        """用 API 返回的结构化数据构建 prompt"""
        lines = [f"# 问题:\n{question}\n", "# 事实数据（来自金融 API）:"]
        field_map = {
            "management_fee": "管理费率",
            "custody_fee": "托管费率",
            "subscription_fee": "最高申购费率",
            "redemption_fee": "最高赎回费率",
            "nav": "最新净值",
            "nav_date": "净值日期",
            "scale": "基金规模",
            "fund_manager": "基金管理人",
            "custodian": "基金托管人",
            "fund_type": "基金类型",
        }
        for key, label in field_map.items():
            val = api_data.get(key, "")
            if val:
                lines.append(f"- {label}: {val}")
        lines.append(f"\n基金代码: {api_data.get('fund_code', '未知')}")
        lines.append("\n# 指令:\n请根据以上事实数据，用简洁自然的语言回答用户问题。直接给出准确数字，不要模糊表述。")
        return "\n".join(lines)

    def _build_market_prompt(self, question: str, data: dict) -> str:
        """构建行情数据 prompt（新增）"""
        return f"""# 问题:
{question}

# 实时行情数据（来自金融 API）:
- 基金名称: {data.get('name', '')} ({data.get('code', '')})
- 最新价: {data.get('price', 0)} 元
- 涨跌幅: {data.get('change_pct', 0)}%
- 涨跌额: {data.get('change', 0)} 元
- 昨收: {data.get('prev_close', 0)} 元

# 日内行情:
- 今开: {data.get('open', 0)} 元
- 最高: {data.get('high', 0)} 元
- 最低: {data.get('low', 0)} 元
- 振幅: {data.get('amplitude', 0)}%

# 成交数据:
- 成交量: {data.get('volume', 0):,.0f} 份
- 成交额: {data.get('amount', 0):,.0f} 元
- 换手率: {data.get('turnover_rate', 0)}%

# 盘口:
- 买一: {data.get('bid_price', 0)} 元
- 卖一: {data.get('ask_price', 0)} 元
- 委比: {data.get('order_ratio', 0)}%

# 资金流向:
- 主力净流入: {data.get('main_inflow', 0):,.0f} 元 ({data.get('main_inflow_pct', 0)}%)

# 指令:
请用简洁自然的语言回答用户问题。重点说明涨跌幅和价格变化。
数据更新时间: {data.get('update_time', '')}
"""

    def _build_ranking_prompt(self, question: str, results: list) -> str:
        """构建榜单 prompt（新增）"""
        sort_label = "涨幅" if not any(k in question for k in ["跌", "跌幅"]) else "跌幅"
        lines = [f"# 问题:\n{question}\n\n# ETF{sort_label}榜（来自金融 API）:", ""]
        lines.append("| 排名 | 代码 | 名称 | 最新价 | 涨跌幅(%) | 成交额 |")
        lines.append("|------|------|------|--------|-----------|--------|")
        for i, item in enumerate(results, 1):
            amount_str = f"{item.get('amount', 0) / 1e8:.2f}亿" if item.get('amount', 0) > 1e8 else f"{item.get('amount', 0) / 1e4:.2f}万"
            lines.append(
                f"| {i} | {item.get('code', '')} | {item.get('name', '')} | "
                f"{item.get('price', 0):.3f} | {item.get('change_pct', 0):.2f} | {amount_str} |"
            )
        lines.append(f"\n# 指令:\n请根据以上{sort_label}榜数据，用简洁自然的语言回答用户问题。可以突出前3名的关键数据。")
        return "\n".join(lines)

    def _boost_by_doc_type(self, chunks: list, question: str) -> list:
        """对事实类问题（费率等），给专业文档类型的 chunk 加权"""
        if not self._is_fee_question(question):
            return chunks
        for chunk in chunks:
            doc_type = chunk.get("doc_type", "other")
            if doc_type == "prospectus":
                boost = 1.5
            elif doc_type == "guide":
                boost = 0.7
            else:
                boost = 1.0
            chunk["rrf_score"] = chunk.get("rrf_score", 0.0) * boost
        return sorted(chunks, key=lambda c: c.get("rrf_score", 0.0), reverse=True)

    def _extract_rate_value(self, text: str, label: str) -> str:
        if not text:
            return ""
        patterns = [
            rf"{label}[^。\n]*?(\d+(?:\.\d+)?)\s*%",
            rf"{label}[^。\n]*?年费率[^。\n]*?(\d+(?:\.\d+)?)\s*%",
            rf"{label}[^。\n]*?费率[^。\n]*?(\d+(?:\.\d+)?)\s*%",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return f"{match.group(1)}%"
        return ""

    def _is_specific_fee_chunk(self, text: str) -> bool:
        """判断文本是否包含具体基金的费率计提规则（而非通用科普描述）"""
        specific_indicators = ("年费率计提", "基金资产净值", "按前一日", "计提标准", "招募说明书")
        generic_indicators = ("通常", "一般", "大约", "左右", "市面上", "常见")
        has_specific = any(ind in text for ind in specific_indicators)
        has_generic = any(ind in text for ind in generic_indicators)
        return has_specific and not has_generic

    def _build_fee_card(self, question: str, top_chunks: list) -> dict:
        card = {
            "is_fee_question": self._is_fee_question(question),
            "management_fee": "",
            "custody_fee": "",
            "subscription_fee": "",
            "redemption_fee": "",
            "evidence": [],
        }

        if not card["is_fee_question"]:
            return card

        texts = []
        for chunk in top_chunks or []:
            text_content = chunk.get("content", "") if isinstance(chunk, dict) else getattr(chunk, "content", "")
            if text_content:
                texts.append(text_content)

        # 优先从包含具体计提规则的文本块中提取费率（如招募书）
        specific_texts = [t for t in texts if self._is_specific_fee_chunk(t)]
        general_texts = [t for t in texts if not self._is_specific_fee_chunk(t)]

        for field, label in [
            ("management_fee", "管理费"),
            ("custody_fee", "托管费"),
            ("subscription_fee", "申购费"),
            ("redemption_fee", "赎回费"),
        ]:
            # 先从具体文档提取
            for text in specific_texts:
                value = self._extract_rate_value(text, label)
                if value:
                    card[field] = value
                    break
            # 兜底：从通用文档提取
            if not card[field]:
                for text in general_texts:
                    value = self._extract_rate_value(text, label)
                    if value:
                        card[field] = value
                        break

        for text in texts[:5]:
            if any(term in text for term in ("管理费", "托管费", "申购费", "赎回费", "%")):
                card["evidence"].append(text[:180].replace("\n", " "))

        return card
        
    def _rerank_and_select(self, candidate_chunks, retrieval_query, top_k):
        """对候选 chunk 做 rerank 并返回 top_k 结果"""
        if not candidate_chunks or not getattr(self, "reranker", None):
            logger.debug("由于没有挂载 reranker 或无候选，回退至纯向量模型")
            return candidate_chunks[:top_k]

        logger.debug(f"进入 Reranker: 正在使用 {self.reranker.model.name_or_path} 过滤 {len(candidate_chunks)} 候选内容...")
        pairs = [
            [retrieval_query, chunk.get('content', '') if isinstance(chunk, dict) else getattr(chunk, 'content', '')]
            for chunk in candidate_chunks
        ]
        scores = self.reranker.predict(pairs)

        for i, chunk in enumerate(candidate_chunks):
            if isinstance(chunk, dict):
                chunk['rerank_score'] = float(scores[i])
            else:
                setattr(chunk, 'rerank_score', float(scores[i]))

        candidate_chunks.sort(
            key=lambda x: x.get('rerank_score', 0) if isinstance(x, dict) else getattr(x, 'rerank_score', 0),
            reverse=True,
        )
        top = candidate_chunks[:top_k]

        for idx, c in enumerate(top):
            score = c.get('rerank_score', 0) if isinstance(c, dict) else getattr(c, 'rerank_score', 0)
            old_score = c.get('similarity', 0) if isinstance(c, dict) else getattr(c, 'similarity', 0)
            logger.debug(f"-> Top {idx+1}: 重排得分 = {score:.4f} | 原向量相似度 = {old_score:.4f}")

        return top

    def _check_rejection(self, top, decision_dict, format_analysis, question=""):
        """检查 top chunk 分数是否低于拒识阈值，返回兜底结果或 None"""
        if not top:
            return self._handle_no_results(decision_dict, format_analysis, question)

        top_score = top[0].get('rerank_score', 0) if isinstance(top[0], dict) else getattr(top[0], 'rerank_score', 0)
        if top_score >= self.RERANK_THRESHOLD:
            return None

        logger.warning(f"检索内容不相关（Top1 得分 {top_score:.4f} < 阈值 {self.RERANK_THRESHOLD}）")
        return self._handle_no_results(decision_dict, format_analysis, question)

    def _handle_no_results(self, decision_dict, format_analysis, question):
        """无相关结果时的分层处理：ETF 相关给引导，非 ETF 直接拒识"""
        if self._is_etf_related(question):
            logger.info("知识库无匹配但问题与 ETF 相关，返回引导提示")
            fallback_prompt = (
                f"# Question:\n{question}\n\n"
                "# Instructions:\n"
                "用户提了一个与 ETF/基金投资相关的问题，但当前知识库中没有直接相关的内容。\n"
                "请根据你的通用金融知识给出简要回答，并在回答开头明确说明：\n"
                "「以下回答来自通用知识，非专业投资建议，具体以基金公司官方公告为准。」\n"
                "如果问题涉及具体投资决策（如是否买入），请建议用户咨询专业投资顾问。\n"
            )
            return {
                "prompt": fallback_prompt,
                "decision": decision_dict,
                "top_chunks": [],
                "format_analysis": format_analysis,
                "fee_card": {"is_fee_question": False},
                "source": "fallback",
            }

        logger.info("问题与 ETF 无关，触发拒识")
        return {
            "prompt": None,
            "decision": decision_dict,
            "top_chunks": [],
            "format_analysis": format_analysis,
            "fee_card": {"is_fee_question": False},
            "source": "rejected",
        }

    def handle_question(self, question: str, doc_id: str = None):
        """
        处理用户问题
        
        参数:
            question: 用户的问题
            doc_id: 限制搜索范围的文档ID（可选）
            
        返回:
            包含提示词、决策结果和相关文本块的字典
        """
        logger.debug(f"开始处理问题: {question}")
        logger.debug(f"文档ID过滤: {doc_id}")

        normalized_question = self._normalize_question(question)
        retrieval_query = self._build_retrieval_query(normalized_question)
        
        # 分析问题意图和输出格式
        logger.debug("开始分析问题意图")
        decision: DecisionResult = self.agent.analyze(normalized_question)
        logger.debug(f"问题分析完成，结果: {decision}")

        # P2: 事实查询走 API（费率/净值/规模），不再让大模型从文档猜
        if decision.intent == "factual_query" or self._is_fee_question(normalized_question):
            api_result = self.finance_api.query(normalized_question)
            if api_result:
                logger.debug(f"API 查询成功: {api_result}")
                return {
                    "prompt": self._build_api_prompt(normalized_question, api_result),
                    "decision": decision,
                    "top_chunks": [],
                    "format_analysis": {"primary_format": "text"},
                    "fee_card": api_result,
                    "source": "api",
                }
            logger.debug("API 查询失败，降级到 RAG")

        # P2: 行情查询走 API（实时行情）（新增）
        if decision.intent == "market_query":
            api_result = self.finance_api.query(normalized_question)
            if api_result:
                logger.debug(f"行情API查询成功: {api_result.get('name', '')}")
                return {
                    "prompt": self._build_market_prompt(normalized_question, api_result),
                    "decision": decision,
                    "top_chunks": [],
                    "format_analysis": {"primary_format": "text"},
                    "fee_card": {"is_fee_question": False},
                    "source": "api",
                }
            logger.debug("行情API查询失败，降级到 RAG")

        # P2: 榜单查询（新增）
        if decision.intent == "ranking_query":
            # 解析排序方向：含"跌"字按跌幅排序，否则按涨幅排序
            ascending = "跌" in normalized_question
            results = self.finance_api.query_ranking(ascending=ascending, top_n=decision.top_k)
            return {
                "prompt": self._build_ranking_prompt(normalized_question, results),
                "decision": decision,
                "top_chunks": [],
                "format_analysis": {"primary_format": "table"},
                "fee_card": {"is_fee_question": False},
                "source": "api",
            }

        # 使用输出格式智能体分析输出格式
        logger.debug("使用输出格式智能体分析输出格式")
        format_analysis = self.output_format_agent.analyze(
            intent=decision.intent,
            content="",  # 在此阶段上下文内容为空，可扩展为使用检索到的内容
            user_preference=None
        )
        logger.debug(f"输出格式分析完成，结果: {format_analysis}")
        
        # 生成问题的嵌入向量
        logger.debug("生成问题嵌入向量")
        qvec = self.embedder.embed_text(retrieval_query)
        logger.debug(f"问题嵌入向量生成完成，维度: {len(qvec)}")
        
        #TODO：封装一个类似的函数，以后可以直接调用打印预览
        # 打印向量预览，输出完整向量
        # logger.debug(f"问题向量完整内容: {qvec}")
        
        # 检索相关文本块 (重排 RAG 2.0 护城河)
        initial_top_k = 100 if self._is_fee_question(normalized_question) else 20
        logger.debug(f"开始检索相关文本块，第一阶段扩大候选集 top_k: {initial_top_k}")
        candidate_chunks = self.retriever.retrieve(
            qvec,
            top_k=initial_top_k,
            doc_id=doc_id,
            query_text=retrieval_query,
        )
        logger.debug(f"初步检索完成，返回 {len(candidate_chunks)} 个候选文本块")

        if self._is_fee_question(normalized_question):
            fee_chunks = self._prefilter_fee_chunks(candidate_chunks)
            if fee_chunks:
                logger.debug(f"费率问题触发预过滤：从 {len(candidate_chunks)} 缩减到 {len(fee_chunks)} 条费用相关候选")
                candidate_chunks = fee_chunks

        # 按文档类型加权（费率问题优先取招募书等专业文档）
        candidate_chunks = self._boost_by_doc_type(candidate_chunks, normalized_question)

        # 交叉注意力重排序过滤
        top = self._rerank_and_select(candidate_chunks, retrieval_query, decision.top_k)

        # 第一道防线：rerank 分数阈值拒识
        rejected = self._check_rejection(top, decision.__dict__, format_analysis, normalized_question)
        if rejected:
            return rejected

        # 构建完整提示词
        logger.debug("开始构建提示词")
        prompt = build_prompt(question, decision.__dict__, top, format_analysis)
        logger.debug(f"提示词构建完成，长度: {len(prompt)}")

        # 输出完整的prompt内容（限制为前1000个字符）
        # logger.debug(f"完整提示词内容:\n{prompt[:1000]}{'...' if len(prompt) > 1000 else ''}")
        # logger.debug(f"完整提示词内容:\n{prompt[:]}{'...' if len(prompt) > 1000 else ''}")
        logger.debug(f"完整提示词内容:\n{format_prompt_for_log(prompt)}")

        fee_card = self._build_fee_card(question, top)
        result = {
            "prompt": prompt,
            "decision": decision.__dict__,
            "top_chunks": top,
            "format_analysis": format_analysis,
            "fee_card": fee_card,
        }
        logger.debug("问答处理完成")
        return result
    
def format_prompt_for_log(prompt: str) -> str:
    if len(prompt) <= 600:
        return prompt
    return f"{prompt[:500]}...{prompt[-100:]}"
