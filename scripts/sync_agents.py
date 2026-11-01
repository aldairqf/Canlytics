"""Generate the Codex agent config from the Claude one (single source of truth: .claude/).

.claude/agents/<name>.md    -> .codex/agents/<name>.toml
.claude/commands/<name>.md  -> .agents/skills/source-command-<name>/SKILL.md

Usage: python scripts/sync_agents.py [--check]   (--check exits 1 if anything is stale)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CLAUDE_COMMANDS = ROOT / ".claude" / "commands"
CODEX_AGENTS = ROOT / ".codex" / "agents"
CODEX_SKILLS = ROOT / ".agents" / "skills"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, header, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in header.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"')
    return meta, body.lstrip("\n")


def _toml_str(value: str) -> str:
    if '"' in value:
        return f'"""{value}"""'
    return f'"{value}"'


def _for_codex(text: str) -> str:
    return text.replace("CLAUDE.md", "AGENTS.md")


def render_agent(path: Path) -> str:
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    name = meta.get("name", path.stem)
    description = _for_codex(meta.get("description", ""))
    instructions = _for_codex(body.rstrip()).replace('"""', '\\"\\"\\"')
    return (
        f"name = {_toml_str(name)}\n"
        f"description = {_toml_str(description)}\n"
        f'developer_instructions = """\n{instructions}"""\n'
    )


def render_skill(path: Path) -> str:
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    name = f"source-command-{path.stem}"
    description = _for_codex(meta.get("description", "")).replace('"', "'")
    return (
        f'---\nname: "{name}"\ndescription: "{description}"\n---\n\n'
        f"# {name}\n\n"
        f"Use this skill when the user asks to run the migrated source command `{path.stem}`.\n\n"
        f"## Command Template\n\n{_for_codex(body).rstrip()}\n"
    )


def expected_files() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for src in sorted(CLAUDE_AGENTS.glob("*.md")):
        files[CODEX_AGENTS / f"{src.stem}.toml"] = render_agent(src)
    for src in sorted(CLAUDE_COMMANDS.glob("*.md")):
        files[CODEX_SKILLS / f"source-command-{src.stem}" / "SKILL.md"] = render_skill(src)
    return files


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for path, content in expected_files().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        stale.append(path.relative_to(ROOT))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    for rel in stale:
        print(("stale: " if check else "wrote: ") + str(rel))
    if check and stale:
        print("Run: python scripts/sync_agents.py")
        return 1
    if not stale:
        print("Codex config in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
