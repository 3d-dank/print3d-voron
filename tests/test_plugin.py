import json
import tomllib
from pathlib import Path

from print3d.paths import skill_dir

ROOT = Path(__file__).resolve().parents[1]


def test_hermes_plugin_matches_the_package():
    manifest = json.loads((ROOT / "plugin.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]
    assert (ROOT / "skills" / "print3d").resolve() == skill_dir()
    server = json.loads((ROOT / "mcp.json").read_text())["mcpServers"]["print3d"]
    assert server["args"][-2:] == ["print3d", "mcp"]
    hermes = manifest["extensions"]["com.nousresearch.hermes"]
    assert hermes["servers"]["print3d"]["trust"] == "untrusted"
