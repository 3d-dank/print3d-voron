"""The seam between the pipeline and a slicer: parts in, per-plate G-code and a review project out."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from print3d.printer import Printer


class SlicerError(RuntimeError):
    """Raised for slicer discovery, placement or slice failures."""


@dataclass(frozen=True)
class Part:
    """One printed mesh. Parts sharing `object` and `plate` are volumes of one object."""

    name: str
    stl: Path
    tool: int  # 1-based extruder
    plate: int = 1
    object: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SliceJob:
    printer: Printer
    parts: list[Part]
    out_dir: Path
    slug: str
    colours: tuple[str, ...] = ()  # colours[i] is the colour name for tool i + 1
    material: str | None = None


@dataclass(frozen=True)
class PlateResult:
    index: int
    gcode: Path
    png: Path | None
    review_3mf: Path
    grams_by_tool: dict[int, float]
    weight_g: float | None


@dataclass(frozen=True)
class SliceResult:
    returncode: int
    plates: list[PlateResult]
    output: Path
    output_size_bytes: int
    review_3mf: Path
    log: str = ""


class Slicer(Protocol):
    def plan(self, job: SliceJob) -> dict[str, Any]: ...

    def slice(self, job: SliceJob, timeout_s: float = 180) -> SliceResult: ...


def slicer_for(printer: Printer) -> Slicer:
    if printer.backend == "bambu":
        from print3d.bambu_slicer import BambuStudio

        return BambuStudio()
    from print3d.prusa_slicer import PrusaSlicer

    return PrusaSlicer()
