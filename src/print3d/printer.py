"""The printer profile layer: one folder per printer under profiles/."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from print3d.paths import PACKAGE

PRINTER_ENV = "PRINT3D_PRINTER"
DEFAULT_PRINTER = "voron300-sc"
BACKENDS = ("prusaslicer", "bambu")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


class PrinterError(ValueError):
    """Raised for an unknown printer, material or a broken printer.toml."""


@dataclass(frozen=True)
class Tool:
    index: int  # 1-based, the slicer's extruder number
    klipper: str
    nozzle_mm: float
    head: str


@dataclass(frozen=True)
class Printer:
    key: str
    name: str
    dir: Path
    backend: str
    bed_mm: tuple[float, float, float]
    bed_exclude: tuple[tuple[float, float, float, float], ...]
    tools: tuple[Tool, ...]
    default_material: str
    materials: dict[str, str] = field(default_factory=dict)

    @property
    def nozzle_mm(self) -> float:
        return self.tools[0].nozzle_mm

    def config_for(self, material: str | None = None) -> Path:
        """The slicer config file for a material (default: the printer's default)."""
        wanted = (material or self.default_material).upper()
        known = {key.upper(): value for key, value in self.materials.items()}
        if wanted not in known:
            raise PrinterError(
                f"{self.key} has no {wanted} config. Materials: {', '.join(sorted(known)) or 'none'}."
            )
        return self.dir / known[wanted]


def profiles_root() -> Path:
    return PACKAGE / "profiles"


def list_printers() -> list[str]:
    root = profiles_root()
    return sorted(p.name for p in root.iterdir() if (p / "printer.toml").is_file()) if root.is_dir() else []


def load_printer(name: str | None = None) -> Printer:
    key = name or os.environ.get(PRINTER_ENV, "").strip() or DEFAULT_PRINTER
    if not NAME_RE.fullmatch(key) or ".." in key:
        raise PrinterError(f"printer {key!r}: use 1 to 64 of a-z, 0-9, _, - and . (not leading)")
    folder = profiles_root() / key
    manifest = folder / "printer.toml"
    if not manifest.is_file():
        raise PrinterError(f"Unknown printer {key!r}. Known printers: {', '.join(list_printers())}.")
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        backend = data.get("backend", "prusaslicer")
        if backend not in BACKENDS:
            raise PrinterError(f"{manifest}: backend must be one of {', '.join(BACKENDS)}")
        tools = tuple(
            Tool(i, t.get("klipper", ""), float(t["nozzle_mm"]), t.get("head", ""))
            for i, t in enumerate(data["tools"], start=1)
        )
        if not tools:
            raise PrinterError(f"{manifest}: needs at least one [[tools]] entry")
        bed = tuple(float(v) for v in data["bed_mm"])
        if len(bed) != 3:
            raise PrinterError(f"{manifest}: bed_mm is [x, y, z]")
        return Printer(
            key=key,
            name=data["name"],
            dir=folder,
            backend=backend,
            bed_mm=bed,  # type: ignore[arg-type]
            bed_exclude=tuple(tuple(float(v) for v in rect) for rect in data.get("bed_exclude", [])),  # type: ignore[misc]
            tools=tools,
            default_material=data.get("default_material", "PLA"),
            materials=dict(data.get("materials", {})),
        )
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        raise PrinterError(f"{manifest}: {exc!r}") from exc
