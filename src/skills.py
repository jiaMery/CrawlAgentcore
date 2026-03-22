"""Load Agent Skills from skills/<skill-name>/SKILL.md directories.

Follows the Agent Skills open standard:
- Each skill is a directory with SKILL.md as the entrypoint
- YAML frontmatter provides metadata (name, description, argument-hint)
- $ARGUMENTS is replaced with the user's input at invocation time
- $ARGUMENTS[N] / $N access positional arguments
- Supporting files (examples, reference docs) live alongside SKILL.md
"""

import os
import re
from dataclasses import dataclass, field

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")
DEFAULT_SKILL = "default-crawl"


@dataclass
class Skill:
    name: str
    description: str
    argument_hint: str
    content: str
    directory: str
    supporting_files: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 3:].strip()
    meta: dict = {}
    for line in fm_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, body


def _substitute_arguments(content: str, arguments: str) -> str:
    """Replace $ARGUMENTS, $ARGUMENTS[N], and $N placeholders."""
    parts = arguments.split() if arguments else []

    # $ARGUMENTS[N] and $N — positional
    def _pos_replace(match: re.Match) -> str:
        idx = int(match.group(1))
        return parts[idx] if idx < len(parts) else ""

    content = re.sub(r"\$ARGUMENTS\[(\d+)\]", _pos_replace, content)
    content = re.sub(r"\$(\d+)", _pos_replace, content)

    # $ARGUMENTS — full string
    content = content.replace("$ARGUMENTS", arguments)
    return content


def _discover_supporting_files(skill_dir: str) -> list[str]:
    """List supporting files relative to the skill directory."""
    files: list[str] = []
    for root, _, filenames in os.walk(skill_dir):
        for f in filenames:
            if f == "SKILL.md":
                continue
            files.append(os.path.relpath(os.path.join(root, f), skill_dir))
    return sorted(files)


def load_skill(name: str, arguments: str = "") -> Skill:
    """Load a skill by directory name, applying $ARGUMENTS substitution.

    Falls back to the default skill if *name* is not found.
    """
    skill_dir = os.path.join(SKILLS_DIR, name)
    skill_md = os.path.join(skill_dir, "SKILL.md")

    if not os.path.isfile(skill_md):
        skill_dir = os.path.join(SKILLS_DIR, DEFAULT_SKILL)
        skill_md = os.path.join(skill_dir, "SKILL.md")

    with open(skill_md, "r") as f:
        raw = f.read()

    meta, body = _parse_frontmatter(raw)
    body = _substitute_arguments(body, arguments)

    return Skill(
        name=meta.get("name", name),
        description=meta.get("description", ""),
        argument_hint=meta.get("argument-hint", ""),
        content=body,
        directory=skill_dir,
        supporting_files=_discover_supporting_files(skill_dir),
    )


def load_supporting_file(skill_name: str, relative_path: str) -> str:
    """Read a supporting file from a skill directory."""
    path = os.path.join(SKILLS_DIR, skill_name, relative_path)
    with open(path, "r") as f:
        return f.read()


def list_skills() -> list[dict]:
    """Return metadata for all available skills."""
    skills: list[dict] = []
    for entry in sorted(os.listdir(SKILLS_DIR)):
        skill_md = os.path.join(SKILLS_DIR, entry, "SKILL.md")
        if os.path.isfile(skill_md):
            with open(skill_md, "r") as f:
                meta, _ = _parse_frontmatter(f.read())
            skills.append({
                "name": meta.get("name", entry),
                "description": meta.get("description", ""),
                "argument_hint": meta.get("argument-hint", ""),
            })
    return skills
