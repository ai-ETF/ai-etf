"""
风险画像服务

提供风险问卷的读取、答案提交、画像计算与存储功能。
使用 Supabase 存储，user_id 来自 JWT 认证（Supabase auth.users 的 UUID）。
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# 风险等级阈值
THRESHOLD_CONSERVATIVE = 1.6  # ≤ 1.6 → 保守型
THRESHOLD_MODERATE = 2.4      # 1.6 < x ≤ 2.4 → 稳健型; > 2.4 → 进取型

# 画像等级元信息
RISK_LEVELS = {
    "conservative": {"label": "保守型",  "summary": "您属于保守型投资者，倾向于低风险、稳定回报的投资方式，注重本金安全和流动性。"},
    "moderate":     {"label": "稳健型",  "summary": "您属于稳健型投资者，在控制风险的前提下追求适度收益，风险与收益并重。"},
    "aggressive":   {"label": "进取型",  "summary": "您属于进取型投资者，愿意承担较高风险以换取更高的长期投资回报。"},
}

# ==================== 交易风险提示 ====================

# 警告矩阵：用户画像 × 基金风险等级 → 提示级别（None = 无需提示）
RISK_WARNING_MATRIX = {
    "conservative": {"moderate": "info", "aggressive": "warning", "speculative": "alert"},
    "moderate":     {"moderate": None,   "aggressive": "info",    "speculative": "warning"},
    "aggressive":   {"moderate": None,   "aggressive": None,      "speculative": "info"},
}

# 建议配置比例（%）矩阵：仅 warning/alert 级携带；info 级模板无比例占位符，不携带
SUGGESTED_PCT_MATRIX = {
    "conservative": {"aggressive": 10, "speculative": 5},
    "moderate":     {"speculative": 15},
}


def _build_warning_message(level: str, user_risk_label: str,
                           fund_risk_label: str, suggested_pct) -> str:
    """按提示级别构建消息文本"""
    if level == "info":
        return (
            f"ETF 均属于权益类投资产品，存在本金损失风险。该基金风险等级为 **{fund_risk_label}**，"
            f"与您 **{user_risk_label}** 的风险偏好存在一定差异，请根据自身情况审慎决策。"
        )
    if level == "warning":
        return (
            f"⚠️ 该基金风险等级为 **{fund_risk_label}**，超出您 **{user_risk_label}** 的风险承受范围。"
            f"建议：① 控制该基金配置比例不超过总资产的 **{suggested_pct}%**；"
            f"② 结合自身投资期限和回撤承受能力综合评估。"
        )
    # alert
    return (
        f"🔴 该基金为 **{fund_risk_label}** 品种，与您 **{user_risk_label}** 的风险偏好存在显著差异。"
        f"强烈建议：① 重新评估是否配置此类高风险产品；"
        f"② 如确需配置，建议比例不超过 **{suggested_pct}%**；"
        f"③ 做好承受较大回撤的准备。"
    )


def _build_risk_warning(user_risk_level: str, user_risk_label: str,
                        fund_risk_level: str, fund_risk_label: str) -> Optional[dict]:
    """查警告矩阵生成风险提示 dict；无需提示返回 None"""
    level = RISK_WARNING_MATRIX.get(user_risk_level, {}).get(fund_risk_level)
    if not level:
        return None

    suggested_pct = None
    if level in ("warning", "alert"):
        suggested_pct = SUGGESTED_PCT_MATRIX.get(user_risk_level, {}).get(fund_risk_level)

    return {
        "level": level,
        "fund_risk_level": fund_risk_level,
        "fund_risk_label": fund_risk_label,
        "user_risk_level": user_risk_level,
        "user_risk_label": user_risk_label,
        "message": _build_warning_message(level, user_risk_label, fund_risk_label, suggested_pct),
        "suggested_max_pct": suggested_pct,
    }


class RiskService:
    """风险画像服务"""

    QUESTIONNAIRE_TABLE = "risk_questionnaires"
    ANSWERS_TABLE = "user_risk_answers"
    PROFILE_TABLE = "user_risk_profiles"

    def __init__(self):
        from server.storage.supabase_client import get_supabase
        self._client = get_supabase()

    # ==================== 公开方法 ====================

    def get_active_questionnaire(self) -> Optional[dict]:
        """
        获取当前最新可用的问卷（is_active=true，按版本降序取第一条）。

        返回:
            { "id": str, "version": str, "questions": list } 或 None
        """
        if not self._client:
            logger.error("数据库连接失败")
            return None

        try:
            result = (
                self._client.table(self.QUESTIONNAIRE_TABLE)
                .select("*")
                .eq("is_active", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                logger.warning("没有找到可用的风险问卷")
                return None
            return result.data[0]
        except Exception as e:
            logger.error(f"获取问卷失败: {e}")
            return None

    def submit_answers(self, user_id: str, questionnaire_id: str, answers: list) -> dict:
        """
        提交问卷答案，计算画像并存储。

        参数:
            user_id: 用户 UUID
            questionnaire_id: 问卷 UUID
            answers: [{"question_id": "q1", "value": "B"}, ...]

        返回:
            成功: {"success": True, "message": "...", "profile": {...}}
            失败: {"success": False, "message": "..."}
        """
        if not self._client:
            return {"success": False, "message": "数据库连接失败"}

        # 1. 获取问卷
        questionnaire = self._get_questionnaire_by_id(questionnaire_id)
        if not questionnaire:
            return {"success": False, "message": "问卷不存在或已停用"}

        questions = questionnaire.get("questions", [])
        if not questions:
            return {"success": False, "message": "问卷题目为空"}

        # 2. 校验答案
        valid, error = self._validate_answers(questions, answers)
        if not valid:
            return {"success": False, "message": error}

        # 3. 计算得分
        score_result = self._calculate_score(questions, answers)

        # 4. 组装画像数据
        profile_data = self._build_profile(
            user_id=user_id,
            questionnaire_id=questionnaire_id,
            answers=answers,
            score_result=score_result,
        )

        # 5. 存入 user_risk_answers
        logger.debug(f"开始保存答题记录: user={user_id}, questionnaire={questionnaire_id}")
        answer_record = self._save_answers(user_id, questionnaire_id, answers)
        if not answer_record:
            logger.error(f"答题记录保存失败: user={user_id}")
            return {"success": False, "message": "保存答题记录失败"}

        # 6. 关联 answer_id 并存入 user_risk_profiles
        profile_data["answer_id"] = answer_record["id"]
        logger.debug(
            f"开始保存画像记录: user={user_id}, answer_id={answer_record['id']}, "
            f"profile_data keys={list(profile_data.keys())}"
        )
        profile_record = self._save_profile(user_id, profile_data)
        if not profile_record:
            # 答案已保存，但画像保存失败，仍可接受
            logger.error(
                f"画像保存失败，但答题记录已保存: user={user_id}, "
                f"answer_id={answer_record['id']}"
            )

        logger.info(
            f"用户画像计算完成: user={user_id}, "
            f"level={profile_data['risk_level']}, "
            f"score={profile_data['total_score']:.2f}"
        )

        return {
            "success": True,
            "message": "问卷提交成功",
            "profile": self._format_profile_result(profile_data),
        }

    def get_latest_profile(self, user_id: str) -> Optional[dict]:
        """
        查询用户最新画像。

        返回:
            有画像: { "risk_level": ..., "risk_label": ..., ... }
            无画像: None
        """
        if not self._client:
            return None

        try:
            result = (
                self._client.table(self.PROFILE_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                logger.info(f"用户 {user_id} 暂无画像")
                return None
            return self._format_profile_result(result.data[0])
        except Exception as e:
            logger.error(f"查询用户画像失败: {e}")
            return None

    @staticmethod
    def get_risk_warning(user_risk_level: str, user_risk_label: str,
                         fund_risk_level: str, fund_risk_label: str) -> Optional[dict]:
        """
        根据用户画像和基金风险等级生成交易风险提示（建议性，不拦截交易）。

        参数:
            user_risk_level:  用户画像等级 (conservative/moderate/aggressive)
            user_risk_label:  用户画像中文标签（入库直接读）
            fund_risk_level:  基金风险等级 (moderate/aggressive/speculative)
            fund_risk_label:  基金风险中文标签（入库直接读）

        返回:
            risk_warning dict，或 None（无需提示）
        """
        return _build_risk_warning(
            user_risk_level, user_risk_label,
            fund_risk_level, fund_risk_label,
        )

    # ==================== 内部方法 ====================

    def _get_questionnaire_by_id(self, questionnaire_id: str) -> Optional[dict]:
        """按 ID 查询问卷"""
        try:
            result = (
                self._client.table(self.QUESTIONNAIRE_TABLE)
                .select("*")
                .eq("id", questionnaire_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"查询问卷失败: {e}")
            return None

    def _validate_answers(self, questions: list, answers: list) -> tuple:
        """
        校验答案合法性。

        返回:
            (True, None) 或 (False, error_message)
        """
        # 检查题目数量
        if len(answers) != len(questions):
            return (False, f"请回答全部 {len(questions)} 道题目")

        # 构建题目索引
        question_map = {q["id"]: q for q in questions}

        # 检查每个答案
        answered_ids = set()
        for ans in answers:
            qid = ans.get("question_id", "")
            value = ans.get("value", "")

            if qid not in question_map:
                return (False, f"题目 {qid} 不存在")

            if qid in answered_ids:
                return (False, f"题目 {qid} 重复作答")

            answered_ids.add(qid)

            # 检查选项值是否合法
            valid_values = {opt["value"] for opt in question_map[qid].get("options", [])}
            if value not in valid_values:
                valid_str = ", ".join(sorted(valid_values))
                return (False, f"题目 {qid} 的选项 \"{value}\" 无效，有效选项: {valid_str}")

        # 检查是否覆盖全部题目
        all_qids = {q["id"] for q in questions}
        if answered_ids != all_qids:
            missing = all_qids - answered_ids
            return (False, f"未回答题目: {', '.join(sorted(missing))}")

        return (True, None)

    def _calculate_score(self, questions: list, answers: list) -> dict:
        """
        计算加权总分和各维度得分。

        返回:
            {
                "total_score": float,
                "weighted_scores": [{"question_id": str, "risk_score": int, "weight": float, "score": float}],
                "dimension_scores": {"category": int, ...},
            }
        """
        question_map = {q["id"]: q for q in questions}
        answer_map = {a["question_id"]: a["value"] for a in answers}

        total_weight = 0.0
        total_weighted_score = 0.0
        weighted_scores = []
        dimension_scores = {}

        for q in questions:
            qid = q["id"]
            selected_value = answer_map[qid]
            weight = q.get("weight", 0)

            # 找到选中选项
            selected_option = None
            for opt in q.get("options", []):
                if opt["value"] == selected_value:
                    selected_option = opt
                    break

            if selected_option is None:
                logger.warning(f"题目 {qid} 未找到选中选项 {selected_value}")
                continue

            risk_score = selected_option.get("risk_score", 0)
            weighted_score = risk_score * weight

            total_weight += weight
            total_weighted_score += weighted_score

            weighted_scores.append({
                "question_id": qid,
                "risk_score": risk_score,
                "weight": weight,
                "score": weighted_score,
            })

            # 维度得分：直接取该题 risk_score
            category = q.get("category", qid)
            dimension_scores[category] = risk_score

        # 计算最终加权总分
        final_score = total_weighted_score / total_weight if total_weight > 0 else 0
        final_score = round(final_score, 2)

        return {
            "total_score": final_score,
            "weighted_scores": weighted_scores,
            "dimension_scores": dimension_scores,
        }

    def _determine_risk_level(self, total_score: float) -> str:
        """根据总分判定风险等级"""
        if total_score <= THRESHOLD_CONSERVATIVE:
            return "conservative"
        elif total_score <= THRESHOLD_MODERATE:
            return "moderate"
        else:
            return "aggressive"

    def _build_profile(self, user_id: str, questionnaire_id: str,
                       answers: list, score_result: dict) -> dict:
        """组装画像数据"""
        risk_level = self._determine_risk_level(score_result["total_score"])
        level_info = RISK_LEVELS[risk_level]

        now = datetime.now(timezone.utc).isoformat()

        return {
            "user_id": user_id,
            "risk_level": risk_level,
            "risk_label": level_info["label"],   # 中文标签入库，避免运行时计算
            "total_score": score_result["total_score"],
            "weighted_scores": score_result["weighted_scores"],
            "dimension_scores": score_result["dimension_scores"],
            "confidence_score": 1.0,
            "ai_summary": level_info["summary"],
            "source": "questionnaire",
            "model_version": "risk-v1",
            "is_active": True,
            "metadata": {"questionnaire_id": questionnaire_id},
            "expires_at": None,
            "created_at": now,
        }

    def _save_answers(self, user_id: str, questionnaire_id: str,
                      answers: list) -> Optional[dict]:
        """保存答题记录，存在则覆盖"""
        try:
            # 将 answers 数组转为 {question_id: value} 对象格式以符合 DB 约束
            answers_dict = {a["question_id"]: a["value"] for a in answers}

            # 先查询是否已有该用户对该问卷的作答
            existing = (
                self._client.table(self.ANSWERS_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .eq("questionnaire_id", questionnaire_id)
                .limit(1)
                .execute()
            )

            now = datetime.now(timezone.utc).isoformat()
            data = {
                "user_id": user_id,
                "questionnaire_id": questionnaire_id,
                "answers": answers_dict,
                "is_completed": True,
                "session_id": None,
                "created_at": now,
            }

            if existing.data:
                # 更新已有记录
                record_id = existing.data[0]["id"]
                result = (
                    self._client.table(self.ANSWERS_TABLE)
                    .update(data)
                    .eq("id", record_id)
                    .execute()
                )
                if result.data:
                    return result.data[0]
                logger.error(f"更新答题记录失败: {record_id}")
                return None
            else:
                # 插入新记录
                result = self._client.table(self.ANSWERS_TABLE).insert(data).execute()
                if result.data:
                    return result.data[0]
                logger.error("插入答题记录失败")
                return None

        except Exception as e:
            logger.error(f"保存答题记录异常: {e}")
            return None

    def _save_profile(self, user_id: str, profile_data: dict) -> Optional[dict]:
        """保存画像记录，存在则覆盖"""
        try:
            logger.debug(
                f"准备写入画像: user_id={user_id}, table={self.PROFILE_TABLE}, "
                f"fields={list(profile_data.keys())}"
            )
            logger.debug(
                f"画像数据详情: risk_level={profile_data.get('risk_level')}, "
                f"source={profile_data.get('source')}, "
                f"model_version={profile_data.get('model_version')}, "
                f"total_score={profile_data.get('total_score')}, "
                f"is_active={profile_data.get('is_active')}"
            )

            # 先查询是否已有该用户的活跃画像
            existing = (
                self._client.table(self.PROFILE_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            logger.debug(f"查询已有画像结果: data_count={len(existing.data) if existing.data else 0}")

            if existing.data:
                # 更新已有画像
                record_id = existing.data[0]["id"]
                logger.debug(f"更新已有画像: id={record_id}")
                result = (
                    self._client.table(self.PROFILE_TABLE)
                    .update(profile_data)
                    .eq("id", record_id)
                    .execute()
                )
                if result.data:
                    logger.info(f"画像更新成功: id={record_id}")
                    return result.data[0]
                logger.error(
                    f"更新画像记录失败: id={record_id}, "
                    f"error_details={getattr(result, 'error', 'unknown')}"
                )
                return None
            else:
                # 插入新画像
                logger.debug(f"插入新画像: user_id={user_id}")
                result = self._client.table(self.PROFILE_TABLE).insert(profile_data).execute()
                if result.data:
                    logger.info(f"画像插入成功: id={result.data[0].get('id')}")
                    return result.data[0]
                logger.error(
                    f"插入画像记录失败: user_id={user_id}, "
                    f"error_details={getattr(result, 'error', 'unknown')}"
                )
                return None

        except Exception as e:
            logger.error(
                f"保存画像记录异常: user_id={user_id}, "
                f"error_type={type(e).__name__}, error={e}"
            )
            return None

    def _format_profile_result(self, profile: dict) -> dict:
        """格式化画像结果为前端可见的 ProfileResult 结构"""
        dim_scores = profile.get("dimension_scores", {})
        if isinstance(dim_scores, str):
            import json
            try:
                dim_scores = json.loads(dim_scores)
            except (json.JSONDecodeError, TypeError):
                dim_scores = {}

        return {
            "risk_level": profile.get("risk_level", ""),
            "risk_label": profile.get("risk_label", ""),
            "total_score": float(profile.get("total_score", 0)),
            "dimension_scores": dim_scores,
            "summary": profile.get("ai_summary", ""),
            "created_at": profile.get("created_at", ""),
        }
