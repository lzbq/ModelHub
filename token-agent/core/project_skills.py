"""实现了项目级 Agent Skill 的加载与注入机制.
它负责从仓库目录 .agents/skills/ 中读取标准化的 SKILL.md 工作流指令文件，最终注入到 LLM 的 system prompt 中，指导 Agent 如何使用工具。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import yaml


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)(.*)\Z", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectSkillError(RuntimeError):
    """Raised when repository Skill configuration is missing or invalid."""

#一个不可变数据类，表示单个 Skill
@dataclass(frozen=True)
class ProjectSkill:
    name: str                #Skill 唯一标识，如 modelhub-model-selection
    description: str         #用途描述，用于判断何时触发
    instructions: str       #SKILL.md 中 frontmatter 之后的 Markdown 指令正文
    path: Path              #对应 SKILL.md 文件路径


class ProjectSkillRegistry:
    """Read standard ``SKILL.md`` bundles from ``.agents/skills``."""

    DEFAULT_DIR = Path(__file__).resolve().parents[1] / ".agents" / "skills"

    def __init__(
        self,
        skills_dir: Optional[str] = None,
        *,
        strict: bool = True,
        max_skill_chars: int = 6000,
        max_total_chars: int = 18000,
    ):
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else self.DEFAULT_DIR
        self.strict = strict
        self.max_skill_chars = max_skill_chars
        self.max_total_chars = max_total_chars
        self._skills: dict[str, ProjectSkill] = {}
        self.reload()

    def reload(self) -> None:
        if not self.skills_dir.is_dir():
            if self.strict:
                raise ProjectSkillError(f"项目 Skill 目录不存在: {self.skills_dir}")
            self._skills = {}
            return

        loaded: dict[str, ProjectSkill] = {}
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            skill = self._load_skill(skill_md)
            if skill.name in loaded:
                raise ProjectSkillError(f"项目 Skill 名称重复: {skill.name}")
            loaded[skill.name] = skill

        if self.strict and not loaded:
            raise ProjectSkillError(f"项目 Skill 目录为空: {self.skills_dir}")
        self._skills = loaded
    #加载单个 Skill
    def _load_skill(self, path: Path) -> ProjectSkill:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as ex:
            raise ProjectSkillError(f"无法读取项目 Skill: {path}") from ex

        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ProjectSkillError(f"SKILL.md frontmatter 格式错误: {path}")
        try:
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError as ex:
            raise ProjectSkillError(f"SKILL.md YAML 无效: {path}") from ex
        if not isinstance(metadata, dict) or set(metadata) != {"name", "description"}:
            raise ProjectSkillError(f"SKILL.md frontmatter 只能包含 name 和 description: {path}")

        name = metadata.get("name")
        description = metadata.get("description")
        instructions = match.group(2).strip()
        if not isinstance(name, str) or not _SKILL_NAME_RE.fullmatch(name):
            raise ProjectSkillError(f"项目 Skill name 无效: {path}")
        if path.parent.name != name:
            raise ProjectSkillError(f"项目 Skill 目录名必须与 name 一致: {path}")
        if not isinstance(description, str) or not description.strip():
            raise ProjectSkillError(f"项目 Skill description 不能为空: {path}")
        if not instructions:
            raise ProjectSkillError(f"项目 Skill 指令不能为空: {path}")
        if len(instructions) > self.max_skill_chars:
            raise ProjectSkillError(f"项目 Skill 指令过长: {name}")

        return ProjectSkill(
            name=name,
            description=description.strip(),
            instructions=instructions,
            path=path,
        )
    # 列表查询：按名称排序返回所有已加载的 Skill。
    def list(self) -> List[ProjectSkill]:
        return [self._skills[name] for name in sorted(self._skills)]

    # 解析 Skill：按名称解析 Skill 列表，并返回 Skill 名称和渲染后的指令。
    def resolve(self, names: Iterable[str]) -> Tuple[List[str], str]:
        resolved: List[ProjectSkill] = []
        missing: List[str] = []
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            skill = self._skills.get(name)
            if skill is None:
                missing.append(name)
            else:
                resolved.append(skill)

        if missing and self.strict:
            raise ProjectSkillError(f"未找到项目 Skill: {', '.join(missing)}")

        blocks = [
            f'<project-skill name="{skill.name}">\n{skill.instructions}\n</project-skill>'
            for skill in resolved
        ]
        rendered = "\n\n".join(blocks)
        if len(rendered) > self.max_total_chars:
            raise ProjectSkillError("本次项目 Skill 指令总长度超过限制")
        return [skill.name for skill in resolved], rendered


__all__ = ["ProjectSkill", "ProjectSkillError", "ProjectSkillRegistry"]
