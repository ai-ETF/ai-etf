"""
Skill 内容加载器

实现渐进式披露：
1. 启动时只加载 frontmatter（~100 tokens/skill）
2. 意图匹配后加载完整 SKILL.md
3. 执行过程中按需加载 references/ 和 assets/ 文件
"""
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    单个 Skill 的内容加载器

    按需加载 Skill 文件，遵循渐进式披露原则。
    """

    def __init__(self, skill_path: Path):
        self.skill_path = Path(skill_path)
        self._full_content_cache: Optional[str] = None
        self._reference_cache: Dict[str, str] = {}
        self._asset_cache: Dict[str, str] = {}

    def load_full_skill(self) -> str:
        """
        加载完整 SKILL.md 内容（body 部分，不含 frontmatter）

        Returns:
            SKILL.md 的主体内容（YAML frontmatter 之后的部分）
        """
        if self._full_content_cache is not None:
            return self._full_content_cache

        skill_md = self.skill_path / "SKILL.md"
        if not skill_md.exists():
            logger.error(f"SKILL.md 不存在: {skill_md}")
            return ""

        content = skill_md.read_text(encoding="utf-8")

        # 去掉 frontmatter，只保留主体
        parts = content.split("---", 2)
        if len(parts) >= 3:
            self._full_content_cache = parts[2].strip()
        else:
            self._full_content_cache = content

        return self._full_content_cache

    def load_frontmatter_text(self) -> str:
        """
        加载 frontmatter 原始文本

        Returns:
            YAML frontmatter 字符串
        """
        skill_md = self.skill_path / "SKILL.md"
        if not skill_md.exists():
            return ""

        content = skill_md.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) >= 2:
            return parts[1].strip()
        return ""

    def load_reference(self, ref_name: str) -> str:
        """
        加载引用文件

        Args:
            ref_name: 文件名（不含 .md 后缀），如 "inquiry"

        Returns:
            引用文件内容
        """
        if ref_name in self._reference_cache:
            return self._reference_cache[ref_name]

        ref_path = self.skill_path / "references" / f"{ref_name}.md"
        if ref_path.exists():
            content = ref_path.read_text(encoding="utf-8")
            self._reference_cache[ref_name] = content
            logger.debug(f"已加载引用文件: {ref_name}")
            return content

        logger.warning(f"引用文件不存在: {ref_path}")
        return ""

    def load_asset(self, asset_name: str) -> str:
        """
        加载资源文件

        Args:
            asset_name: 文件名（不含后缀），如 "exec_plan_template"

        Returns:
            资源文件内容
        """
        if asset_name in self._asset_cache:
            return self._asset_cache[asset_name]

        # 先尝试 .md 后缀
        asset_path = self.skill_path / "assets" / f"{asset_name}.md"
        if asset_path.exists():
            content = asset_path.read_text(encoding="utf-8")
            self._asset_cache[asset_name] = content
            logger.debug(f"已加载资源文件: {asset_name}")
            return content

        # 尝试 assets 子目录
        asset_path = self.skill_path / "assets" / asset_name
        if asset_path.exists() and asset_path.is_dir():
            # 如果是目录，读取目录下的文件
            contents = []
            for f in sorted(asset_path.iterdir()):
                if f.is_file() and f.suffix == ".md":
                    contents.append(f.read_text(encoding="utf-8"))
            result = "\n\n".join(contents)
            self._asset_cache[asset_name] = result
            return result

        logger.warning(f"资源文件不存在: {asset_path}")
        return ""

    def load_config(self) -> Dict:
        """
        加载 config.yaml

        Returns:
            配置字典
        """
        import yaml

        config_path = self.skill_path / "config.yaml"
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")
            return yaml.safe_load(content) or {}
        return {}

    def clear_cache(self):
        """清除缓存"""
        self._full_content_cache = None
        self._reference_cache.clear()
        self._asset_cache.clear()
