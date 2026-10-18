"""Register print3d with the coding agents on this machine.

Each agent gets the MCP server, launched with the Python print3d is installed
in. Claude Code also gets the skill, linked so it follows the installed
package. Nothing is changed until the plan has been shown; every file edited is
backed up beside itself first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from print3d.paths import skill_dir

AGENTS = ("claude", "codex", "cursor", "gemini")
NAME = "print3d"


class SetupError(RuntimeError):
    """Raised when an agent's config cannot be changed safely."""


@dataclass(frozen=True)
class Change:
    agent: str
    target: str
    action: str
    apply: Callable[[], None]

    def describe(self) -> str:
        return f"{self.agent:7} {self.action}  ({self.target})"


def server_command() -> list[str]:
    return [sys.executable, "-m", "print3d", "mcp"]


def _backup(path: Path) -> None:
    if path.exists() or path.is_symlink():
        path.rename(path.with_name(f"{path.name}.print3d-backup-{time.strftime('%Y%m%d-%H%M%S')}"))


def _link(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        _backup(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def _write_with_backup(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.print3d-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    path.write_text(text, encoding="utf-8")


def _merge_mcp_json(path: Path) -> None:
    """Add the server under `mcpServers`, the shape Cursor and Gemini CLI share."""
    try:
        config = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc}); fix it and run setup again.") from exc
    command, *args = server_command()
    config.setdefault("mcpServers", {})[NAME] = {"command": command, "args": args}
    _write_with_backup(path, json.dumps(config, indent=2) + "\n")


CODEX_SECTION = re.compile(rf"^\[mcp_servers\.{NAME}\]\n(?:(?!\[).*\n?)*", re.MULTILINE)


def _merge_codex_toml(path: Path) -> None:
    command, *args = server_command()
    block = (
        f"[mcp_servers.{NAME}]\n"
        f"command = {json.dumps(command)}\n"
        f"args = {json.dumps(args)}\n"
    )
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if CODEX_SECTION.search(text):
        text = CODEX_SECTION.sub(block + "\n", text, count=1)
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    _write_with_backup(path, text)


def _claude_mcp(claude: str, run: Callable[..., subprocess.CompletedProcess]) -> None:
    run([claude, "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True, check=False)
    added = run(
        [claude, "mcp", "add", "--scope", "user", NAME, "--", *server_command()],
        capture_output=True, text=True, check=False,
    )
    if added.returncode != 0:
        raise SetupError(f"claude mcp add failed: {(added.stderr or added.stdout).strip()}")


def detect(home: Path, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    return [agent for agent in AGENTS if which(agent) or (home / f".{agent}").is_dir()]


def plan(
    agents: list[str] | None = None,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[Change]:
    home = home or Path.home()
    changes: list[Change] = []
    for agent in agents or detect(home, which):
        if agent == "claude":
            link = home / ".claude" / "skills" / NAME
            changes.append(Change(agent, str(link), f"link the skill to {skill_dir()}",
                                  lambda link=link: _link(link, skill_dir())))
            if claude := which("claude"):
                changes.append(Change(agent, "user scope", "claude mcp add print3d",
                                      lambda claude=claude: _claude_mcp(claude, run)))
        elif agent == "codex":
            path = home / ".codex" / "config.toml"
            changes.append(Change(agent, str(path), "add [mcp_servers.print3d]",
                                  lambda path=path: _merge_codex_toml(path)))
        elif agent in ("cursor", "gemini"):
            path = home / f".{agent}" / ("mcp.json" if agent == "cursor" else "settings.json")
            changes.append(Change(agent, str(path), "add mcpServers.print3d",
                                  lambda path=path: _merge_mcp_json(path)))
        else:
            raise SetupError(f"Unknown agent {agent!r}; choose from {', '.join(AGENTS)}.")
    return changes
