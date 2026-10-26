"""Bambu Studio backend: today's studio.py flow behind the Slicer interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from print3d.filaments import job_filaments
from print3d.project import extract_plate_png, inspect_project, read_plate_gcode
from print3d.slicer import PlateResult, SliceJob, SlicerError, SliceResult
from print3d.studio import SliceRequest, assemble_list, run_slice, slice_plan


class BambuStudio:
    def _request(self, job: SliceJob) -> SliceRequest:
        profiles = job.printer.dir
        for required in ("machine.json", "process.json", "filament.json"):
            if not (profiles / required).is_file():
                raise SlicerError(
                    f"Pinned profile missing: {profiles / required}. Run: python -m print3d flatten"
                )
        job_dir = job.out_dir.parent
        base = job.printer.config_for(job.material)
        common: dict[str, Any] = dict(
            output_3mf=job.out_dir / f"{job.slug}.gcode.3mf",
            output_project_3mf=job.out_dir / f"{job.slug}.3mf",
            machine=profiles / "machine.json",
            process=profiles / "process.json",
            datadir=job_dir / "studio-datadir",
            output_dir=job.out_dir,
            # Auto-orient would silently rotate the part and invalidate every
            # overhang note. Orientation is the model script's business.
            orient=False,
        )
        if len(job.parts) == 1 and job.parts[0].object is None:
            filaments = (
                tuple(job_filaments(base, list(job.colours), job_dir / "filaments"))
                if job.colours
                else (base,)
            )
            return SliceRequest(input_mesh=job.parts[0].stl, filaments=filaments, **common)

        filaments = tuple(job_filaments(base, list(job.colours), job_dir / "filaments"))
        objects: dict[str, dict[str, Any]] = {}
        for part in job.parts:
            obj = objects.setdefault(part.object or part.name, {"plate": part.plate, "parts": []})
            obj["parts"].append({"stl": part.stl, "filament": part.tool, "settings": part.settings})
        job.out_dir.mkdir(parents=True, exist_ok=True)
        assemble = job.out_dir / "assemble.json"
        assemble.write_text(json.dumps(assemble_list(list(objects.values())), indent=2) + "\n", encoding="utf-8")
        return SliceRequest(input_mesh=job.parts[0].stl, filaments=filaments, assemble_list=assemble, **common)

    def plan(self, job: SliceJob) -> dict[str, Any]:
        return slice_plan(self._request(job))

    def slice(self, job: SliceJob, timeout_s: float = 180) -> SliceResult:
        request = self._request(job)
        done = run_slice(request, timeout_s=timeout_s)
        output = Path(done["output_3mf"])
        review = Path(done["output_project_3mf"])
        inspection = inspect_project(output)
        by_plate = {p["index"]: p for p in inspection["slice_info_parsed"].get("plates", [])}
        multi = len(inspection["plates"]) > 1
        plates = []
        for plate in inspection["plates"]:
            index = plate["index"]
            stem = f"{job.slug}_plate_{index}" if multi else f"{job.slug}_plate"
            gcode = job.out_dir / (f"{job.slug}_plate_{index}.gcode" if multi else f"{job.slug}.gcode")
            gcode.write_text(read_plate_gcode(output, index), encoding="utf-8")
            info = by_plate.get(index, {})
            grams = {int(f["id"]): round(float(f.get("used_g", 0)), 2) for f in info.get("filaments", [])}
            plates.append(
                PlateResult(
                    index,
                    gcode,
                    extract_plate_png(output, job.out_dir / f"{stem}.png", plate=index),
                    review,
                    grams,
                    info.get("weight_g") if info.get("weight_g") is not None else plate["filament_g"],
                )
            )
        return SliceResult(
            returncode=done["returncode"],
            plates=plates,
            output=output,
            output_size_bytes=done["output_size_bytes"],
            review_3mf=review,
            log=(done.get("stdout") or "") + (done.get("stderr") or ""),
        )
