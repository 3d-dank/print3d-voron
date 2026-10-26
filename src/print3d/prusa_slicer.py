"""PrusaSlicer CLI backend: our own 3MF in, a review 3MF and G-code per plate out."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from print3d.filaments import DEFAULT_COLOUR, colour_hex
from print3d.gcode_stats import parse_prusaslicer
from print3d.project_3mf import write_3mf
from print3d.slicer import PlateResult, SliceJob, SlicerError, SliceResult

PRUSASLICER_ENV = "PRUSASLICER_BIN"
PINNED_APP = "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"


def find_prusaslicer() -> Path:
    candidates = [os.environ.get(PRUSASLICER_ENV, "").strip(), PINNED_APP, shutil.which("prusa-slicer") or ""]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return Path(candidate).expanduser().resolve()
    raise SlicerError(f"PrusaSlicer not found. Install 2.9.6 or set {PRUSASLICER_ENV}.")


def _plates(job: SliceJob) -> dict[int, list]:
    by_plate: dict[int, dict[str, list]] = {}
    for part in job.parts:
        by_plate.setdefault(part.plate, {}).setdefault(part.object or part.name, []).append(part)
    return {n: [(name, parts) for name, parts in by_plate[n].items()] for n in sorted(by_plate)}


def _names(job: SliceJob, plate: int, multi: bool) -> dict[str, Path]:
    stem = f"{job.slug}_plate_{plate}" if multi else job.slug
    out = job.out_dir
    return {
        "raw": out / f"{stem}.raw.3mf",
        "review": out / f"{stem}.3mf",
        "gcode": out / f"{stem}.gcode",
        "png": out / (f"{job.slug}_plate_{plate}.png" if multi else f"{job.slug}_plate.png"),
    }


def _overrides(job: SliceJob) -> str:
    names = list(job.colours) or [DEFAULT_COLOUR]
    hexes = [colour_hex(names[i] if i < len(names) else names[0]) for i in range(len(job.printer.tools))]
    joined = ";".join(hexes)
    return f"extruder_colour = {joined}\nfilament_colour = {joined}\n"


def _embed_config(review: Path, *configs: Path) -> None:
    """Add Metadata/Slic3r_PE.config (the export CLI leaves it out) so the 3MF opens with this printer."""
    values: dict[str, str] = {}
    for config in configs:
        for line in config.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(" = ")
            if sep and not key.startswith("#"):
                values[key] = value
    text = "".join(f"; {key} = {value}\n" for key, value in values.items())
    rewritten = review.with_suffix(".tmp")
    with zipfile.ZipFile(review) as source, zipfile.ZipFile(rewritten, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename != "Metadata/Slic3r_PE.config":
                target.writestr(item, source.read(item.filename))
        target.writestr("Metadata/Slic3r_PE.config", text)
    rewritten.replace(review)


class PrusaSlicer:
    def _commands(self, binary: Path, job: SliceJob, plate: int, multi: bool) -> tuple[list[str], list[str]]:
        names = _names(job, plate, multi)
        load = [
            "--datadir", str((job.out_dir.parent / "prusaslicer-datadir").resolve()),
            "--load", str(job.printer.config_for(job.material).resolve()),
            "--load", str((job.out_dir / "overrides.ini").resolve()),
        ]
        project = [str(binary), *load, "--dont-arrange", "--export-3mf", "-o", str(names["review"]), str(names["raw"])]
        gcode = [str(binary), *load, "--dont-arrange", "--export-gcode", "-o", str(names["gcode"]), str(names["review"])]
        return project, gcode

    def plan(self, job: SliceJob) -> dict[str, Any]:
        try:
            binary = find_prusaslicer()
        except SlicerError:
            binary = Path("prusa-slicer")  # a plan is only a preview
        plates = _plates(job)
        multi = len(plates) > 1
        entries = []
        for plate in plates:
            project, gcode = self._commands(binary, job, plate, multi)
            names = _names(job, plate, multi)
            entries.append(
                {"plate": plate, "project_command": project, "command": gcode,
                 "review_3mf": str(names["review"]), "gcode": str(names["gcode"])}
            )
        return {
            "dry_run": True,
            "slicer": str(binary),
            "printer": job.printer.key,
            "config": str(job.printer.config_for(job.material)),
            "plates": entries,
            "command": entries[0]["command"] if entries else [],
            "open_in_studio": entries[0]["review_3mf"] if entries else None,
            "note": "Open the .3mf in PrusaSlicer File > Open; it carries the printer config and the tool per part.",
        }

    def slice(self, job: SliceJob, timeout_s: float = 180) -> SliceResult:
        binary = find_prusaslicer()
        job.out_dir.mkdir(parents=True, exist_ok=True)
        (job.out_dir / "overrides.ini").write_text(_overrides(job), encoding="utf-8")
        plates = _plates(job)
        multi = len(plates) > 1
        results: list[PlateResult] = []
        log: list[str] = []
        for plate, objects in plates.items():
            names = _names(job, plate, multi)
            write_3mf(objects, job.printer.bed_mm, names["raw"], job.printer.bed_exclude)
            for command, target, label in zip(self._commands(binary, job, plate, multi), (names["review"], names["gcode"]), ("project export", "slice")):
                done = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_s)
                log.append(done.stdout)
                if done.returncode != 0 or not target.is_file():
                    raise SlicerError(
                        f"PrusaSlicer {label} failed with exit {done.returncode} (plate {plate}).\n"
                        f"stderr tail:\n{(done.stderr or done.stdout)[-4000:]}"
                    )
                if label == "project export":
                    _embed_config(names["review"], job.printer.config_for(job.material), job.out_dir / "overrides.ini")
            stats = parse_prusaslicer(names["gcode"].read_text(encoding="utf-8", errors="replace"))
            png = None
            if stats.thumbnail_png:
                names["png"].write_bytes(stats.thumbnail_png)
                png = names["png"]
            results.append(
                PlateResult(plate, names["gcode"], png, names["review"], stats.grams_by_tool, stats.filament_g)
            )
        first = results[0]
        return SliceResult(
            returncode=0,
            plates=results,
            output=first.gcode,
            output_size_bytes=first.gcode.stat().st_size,
            review_3mf=first.review_3mf,
            log="\n".join(log),
        )
