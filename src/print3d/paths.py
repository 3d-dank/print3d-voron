"""Where the pinned profiles, the skill and the jobs live."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
JOBS_ENV = "PRINT3D_JOBS"


def repo_root() -> Path:
    return PACKAGE.parents[1]


def default_profiles_dir() -> Path:
    return PACKAGE / "profiles" / "x2d-0.4"


def skill_dir() -> Path:
    return PACKAGE / "skill"


def default_jobs_dir() -> Path:
    """`$PRINT3D_JOBS`, else `jobs/` in a source checkout, else `~/print3d/jobs`."""
    if env := os.environ.get(JOBS_ENV, "").strip():
        return Path(env).expanduser()
    if (repo_root() / "pyproject.toml").is_file():
        return repo_root() / "jobs"
    return Path.home() / "print3d" / "jobs"
