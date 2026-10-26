import shutil
from pathlib import Path

import pytest

from conftest import write_cube_stl
from print3d.printer import load_printer
from print3d.prusa_slicer import PrusaSlicer, find_prusaslicer
from print3d.slicer import Part, SliceJob, SlicerError, slicer_for
from print3d.bambu_slicer import BambuStudio


def _job(tmp_path, parts):
    return SliceJob(load_printer("voron300-sc"), parts, tmp_path / "job" / "slice", "demo", ("red", "blue"))


def test_plan_has_both_loads_and_exports_without_a_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("PRUSASLICER_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr("print3d.prusa_slicer.PINNED_APP", str(tmp_path / "nope"))
    monkeypatch.setattr(shutil, "which", lambda *_: None)
    plan = PrusaSlicer().plan(_job(tmp_path, [Part("a", tmp_path / "a.stl", 1)]))
    project, gcode = plan["plates"][0]["project_command"], plan["plates"][0]["command"]
    assert project.count("--load") == 2 and "--export-3mf" in project
    assert gcode.count("--load") == 2 and "--export-gcode" in gcode
    assert any(a.endswith("pla.ini") for a in gcode) and any(a.endswith("overrides.ini") for a in gcode)
    assert plan["open_in_studio"].endswith("demo.3mf")


def test_two_plates_name_their_files(tmp_path):
    plan = PrusaSlicer().plan(_job(tmp_path, [Part("a", tmp_path / "a.stl", 1), Part("b", tmp_path / "b.stl", 1, plate=2)]))
    assert [p["review_3mf"].rsplit("/", 1)[1] for p in plan["plates"]] == ["demo_plate_1.3mf", "demo_plate_2.3mf"]


def test_backend_picked_by_printer():
    assert isinstance(slicer_for(load_printer("x2d-0.4")), BambuStudio)
    assert isinstance(slicer_for(load_printer("voron300-sc")), PrusaSlicer)


def test_bambu_plan_still_builds(tmp_path):
    job = SliceJob(load_printer("x2d-0.4"), [Part("a", tmp_path / "a.stl", 1)], tmp_path / "job" / "slice", "demo")
    plan = BambuStudio().plan(job)
    assert plan["command"][1] == "--datadir" and plan["open_in_studio"].endswith("demo.3mf")


def _have_prusaslicer():
    try:
        find_prusaslicer()
        return True
    except SlicerError:
        return False


@pytest.mark.skipif(not _have_prusaslicer(), reason="PrusaSlicer not installed")
def test_two_tool_slice_end_to_end(tmp_path):
    cube = write_cube_stl(tmp_path / "cube.stl", 20)
    cyl = write_cube_stl(tmp_path / "cyl.stl", 10)
    job = _job(tmp_path, [Part("cube", cube, 1, object="both"), Part("cyl", cyl, 2, object="both")])
    result = PrusaSlicer().slice(job)
    plate = result.plates[0]
    text = Path(plate.gcode).read_text()
    assert "\nT0" in text and "\nT1" in text
    assert sum(1 for g in plate.grams_by_tool.values() if g > 0) == 2
    assert plate.review_3mf.is_file() and result.output_size_bytes > 0
