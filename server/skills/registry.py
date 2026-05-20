"""
Skill 注册表

启动时扫描所有 SKILL.md 的 YAML frontmatter，构建注册表。
运行时根据用户查询选择最相关的 Skill。
"""
import os
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 默认 Skill 目录
DEFAULT_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills"
)


@dataclass
class SkillMetadata:
    """Skill 元数据（来自 SKILL.md frontmatter）"""
    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    data_requirements: Dict = field(default_factory=dict)
    output: Optional[str] = None
    path: Path = None


class SkillRegistry:
    """
    Skill 注册表

    扫描 skills/ 目录下所有 SKILL.md 的 frontmatter，
    运行时根据用户查询选择最相关的 Skill。
    """

    def __init__(self, skills_dir: Optional[str] = None):
        self.skills_dir = Path(skills_dir or DEFAULT_SKILLS_DIR)
        self.registry: Dict[str, SkillMetadata] = {}
        self._scan_skills()

    def _scan_skills(self):
        """扫描所有 SKILL.md 文件，解析 frontmatter"""
        if not self.skills_dir.exists():
            logger.warning(f"Skill 目录不存在: {self.skills_dir}")
            return

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                metadata = self._parse_frontmatter(skill_md)
                metadata.path = skill_dir
                self.registry[metadata.name] = metadata
                logger.info(f"已注册 Skill: {metadata.name}")
            except Exception as e:
                logger.error(f"解析 Skill 失败 {skill_dir}: {e}")

    def _parse_frontmatter(self, skill_md: Path) -> SkillMetadata:
        """
        解析 SKILL.md 的 YAML frontmatter

        格式：
        ---
        name: buy-decision
        description: ...
        triggers: [...]
        ---
        """
        content = skill_md.read_text(encoding="utf-8")

        # 提取 --- 之间的 frontmatter
        if not content.startswith("---"):
            raise ValueError(f"{skill_md} 缺少 YAML frontmatter")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"{skill_md} frontmatter 格式错误")

        frontmatter_text = parts[1].strip()
        data = yaml.safe_load(frontmatter_text)

        if not data or "name" not in data:
            raise ValueError(f"{skill_md} 缺少 name 字段")

        # 同时读取 config.yaml 获取 data_requirements
        config_path = skill_md.parent / "config.yaml"
        data_requirements = {}
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                if config and "data_requirements" in config:
                    data_requirements = config["data_requirements"]
            except Exception as e:
                logger.warning(f"解析 config.yaml 失败 {config_path}: {e}")

        return SkillMetadata(
            name=data["name"],
            description=data.get("description", ""),
            triggers=data.get("triggers", []),
            examples=data.get("examples", []),
            data_requirements=data_requirements,
            output=data.get("output"),
        )

    def select_skill(self, user_query: str) -> Optional[SkillMetadata]:
        """
        根据用户查询选择最相关的 Skill

        评分逻辑：
        1. triggers 关键词匹配（权重 0.6）
        2. description 关键词匹配（权重 0.4）
        3. 阈值 0.5 以上才返回结果
        """
        if not user_query:
            return None

        query_lower = user_query.lower()
        scores = []

        for name, metadata in self.registry.items():
            score = self._calculate_relevance(query_lower, metadata)
            scores.append((metadata, score))

        scores.sort(key=lambda x: x[1], reverse=True)

        if scores and scores[0][1] > 0.5:
            metadata, score = scores[0]
            logger.info(
                f"选中 Skill: {metadata.name} (score={score:.2f})"
            )
            return metadata

        logger.debug(f"未匹配到 Skill，查询: {user_query}")
        return None

    def _calculate_relevance(self, query_lower: str, metadata: SkillMetadata) -> float:
        """计算查询与 Skill 的相关性分数（0-1）"""
        # 1. Triggers 关键词匹配（权重 0.6）
        trigger_score = 0.0
        for trigger in metadata.triggers:
            if trigger.lower() in query_lower:
                trigger_score = 1.0
                break

        # 2. Description 关键词匹配（权重 0.4）
        desc_score = 0.0
        desc_words = set(metadata.description.lower().split())
        query_words = set(query_lower.split())
        if desc_words & query_words:
            # 命中词占比
            overlap = len(desc_words & query_words) / max(len(desc_words), 1)
            desc_score = min(overlap * 5, 1.0)  # 命中20%以上即给满分

        return trigger_score * 0.6 + desc_score * 0.4

    def get_skill(self, name: str) -> Optional[SkillMetadata]:
        """根据名称获取 Skill 元数据"""
        return self.registry.get(name)

    def list_skills(self) -> List[SkillMetadata]:
        """列出所有已注册的 Skill"""
        return list(self.registry.values())


# 全局单例
_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取 SkillRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
