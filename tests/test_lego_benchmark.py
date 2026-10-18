"""A LEGO 2x4 brick from a photo off the web, scored against LEGO's own dimensions.

The photo is a three-quarter view, as most are. The top face is rectified from
the brick's 31.8 x 15.8 mm footprint, with the back-right corner hidden behind a
stud and found from the two edges that meet there. Everything else is read off
the rectified view, as the agent would, and must land within the tolerance the
tool reports for it.
"""

import json
import math
from pathlib import Path

import pytest

from print3d import spec as specs
from print3d.likeness import check_likeness, likeness_advice
from print3d.photo import meet
from test_likeness import _box, _stl

FIXTURES = Path(__file__).parent / "fixtures"
BENCH = json.loads((FIXTURES / "lego_2x4.json").read_text())
TRUTH = BENCH["lego_mm"]


def build_spec(job_dir: Path) -> dict:
    """The spec an agent builds from the photo, replayed from the recorded points."""
    face = BENCH["top_face"]
    back_right = meet(*face["back_edge"], *face["right_edge"])
    spec = specs.load_spec(job_dir)
    view = specs.rectify_view(
        spec, "top", FIXTURES / "lego_2x4.jpg",
        [face["back_left"], list(back_right), face["front_right"], face["front_left"]],
        tuple(BENCH["face_size_mm"]), job_dir / "views" / "top.png",
    )
    for name, points in BENCH["rectified_points"].items():
        specs.measure_dim(spec, name, "top", points)
    length, width = BENCH["face_size_mm"]
    specs.given_dim(spec, "length", length, "user", None)
    specs.given_dim(spec, "width", width, "user", None)
    specs.given_dim(spec, "height", TRUTH["height"], "user", None)
    specs.given_dim(spec, "stud_height", TRUTH["stud_height"], "assumed",
                    "studs stand off the rectified face, so the top view cannot show their height")
    x0, y0 = view["scale"]["points"][0]
    x1 = view["scale"]["points"][1][0]
    y1 = y0 + width / view["scale"]["mm_per_px"]
    specs.set_outline(spec, "top", points=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    specs.save_spec(job_dir, spec)
    return spec


@pytest.fixture(scope="module")
def spec(tmp_path_factory) -> dict:
    return build_spec(tmp_path_factory.mktemp("lego"))


def _within(spec, name, truth, per=1):
    dim = spec["dims"][name]
    error = abs(dim["mm"] / per - truth)
    assert error <= dim["tolerance_mm"] / per, f"{name}: {dim['mm'] / per:.2f} vs {truth} ± {dim['tolerance_mm'] / per:.2f}"
    return error


def test_hidden_corner_is_found_from_its_edges():
    face = BENCH["top_face"]
    x, y = meet(*face["back_edge"], *face["right_edge"])
    # Opposite corners of the face's quad must sit on either side of the diagonal.
    assert 600 < x < 720 and 90 < y < 150


def test_stud_pitch_along_the_brick(spec):
    assert _within(spec, "stud_span", TRUTH["stud_pitch"], per=3) < 0.1


def test_stud_pitch_across_the_brick(spec):
    assert _within(spec, "row_pitch", TRUTH["stud_pitch"]) < 0.1


def test_stud_margin(spec):
    assert _within(spec, "stud_margin", TRUTH["stud_margin"]) < 0.1


def test_stud_diameter_follows_from_symmetry(spec):
    dims = specs.model_dims(spec)
    diameter = dims["length"] - dims["stud_span"] - 2 * dims["stud_margin"]
    assert diameter == pytest.approx(TRUTH["stud_diameter"], abs=0.15)


def test_every_dimension_says_where_it_came_from(spec):
    sources = {name: dim["source"] for name, dim in spec["dims"].items()}
    assert sources == {
        "stud_span": "measured", "row_pitch": "measured", "stud_margin": "measured",
        "length": "user", "width": "user", "height": "user", "stud_height": "assumed",
    }


def _brick(dims) -> list:
    pitch = dims["stud_span"] / 3
    radius = (dims["length"] - dims["stud_span"]) / 2 - dims["stud_margin"]
    triangles = _box(0, 0, 0, dims["length"], dims["width"], dims["height"])
    for col in range(4):
        for row in range(2):
            cx = dims["length"] / 2 + (col - 1.5) * pitch
            cy = dims["width"] / 2 + (row - 0.5) * dims["row_pitch"]
            top = dims["height"] + dims["stud_height"]
            ring = [(cx + radius * math.cos(a), cy + radius * math.sin(a))
                    for a in (2 * math.pi * i / 32 for i in range(32))]
            triangles += [((cx, cy, top), (*ring[i], top), (*ring[(i + 1) % 32], top)) for i in range(32)]
    return triangles


def test_a_brick_built_from_the_spec_matches_the_photo(tmp_path, spec):
    mesh = _stl(tmp_path / "brick.stl", _brick(specs.model_dims(spec)))
    [result] = check_likeness(mesh, spec, tmp_path / "likeness")
    assert result["iou"] > 0.97
    assert likeness_advice([result])[0].severity == "note"
