"""A shelf bracket rebuilt from its stated sizes, the way a shop listing is used.

The photo is CC0 and the stated dimensions are the photographer's ("20 x 12 cm.
Width: 2 cm. Thickness: 4 mm"), standing in for a listing: nobody measured the
bracket for this. The long leg scales the photo; the other three stated sizes
are measured back off it and scored against what was stated, within its rounding.
"""

import json
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from print3d import spec as specs
from print3d.likeness import check_likeness, likeness_advice
from test_likeness import _box, _stl

FIXTURES = Path(__file__).parent / "fixtures"
BENCH = json.loads((FIXTURES / "bracket.json").read_text())
LISTING = BENCH["listing"]


def build_spec(job_dir: Path) -> dict:
    """The spec an agent builds from the listing and its photo, replayed from the recorded points."""
    spec = specs.load_spec(job_dir)
    specs.set_listing(spec, LISTING["url"], LISTING["name"])
    for name, mm in LISTING["stated_mm"].items():
        specs.listing_dim(spec, name, mm, LISTING["quote"], LISTING["tolerance_mm"][name])
    # Lying on its side, seen from above: the L is in the bed plane.
    specs.set_scale(spec, "top", FIXTURES / "bracket.jpg", f"dim:{BENCH['scale']['dim']}", BENCH["scale"]["points"])
    for name, points in BENCH["checks"].items():
        specs.measure_dim(spec, f"{name}_measured", "top", points)
    for name, points in BENCH["measured"].items():
        specs.measure_dim(spec, name, "top", points)
    for name, (mm, why) in BENCH["assumed"].items():
        specs.given_dim(spec, name, mm, "assumed", why)
    specs.add_unknown(spec, "The holes are seen edge-on: the rim is measured, the bore and any countersink are not.")
    specs.add_unknown(spec, "Steel at 4 mm carries a shelf; PLA at 4 mm will not carry the same load.")
    # The space between the legs and the strut is open, so the outline is a mask, not a polygon.
    mask = Image.new("L", Image.open(FIXTURES / "bracket.jpg").size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([tuple(p) for p in BENCH["outline"]], fill=255)
    draw.polygon([tuple(p) for p in BENCH["window"]], fill=0)
    job_dir.mkdir(parents=True, exist_ok=True)
    mask.save(job_dir / "top_mask.png")
    specs.set_outline(spec, "top", mask=job_dir / "top_mask.png")
    specs.save_spec(job_dir, spec)
    return spec


@pytest.fixture(scope="module")
def spec(tmp_path_factory) -> dict:
    return build_spec(tmp_path_factory.mktemp("bracket"))


def test_scale_comes_from_the_listing(spec):
    scale = spec["views"]["top"]["scale"]
    assert scale["ref"] == "dim:long_leg"
    assert scale["ref_tolerance_mm"] == 5


@pytest.mark.parametrize("name", ["short_leg", "width", "thickness"])
def test_each_stated_size_measures_back_within_its_rounding(spec, name):
    stated, measured = spec["dims"][name], spec["dims"][f"{name}_measured"]
    assert abs(measured["mm"] - stated["mm"]) <= measured["tolerance_mm"] + stated["tolerance_mm"]


def test_the_photo_is_tighter_than_the_rounded_listing(spec):
    # "12 cm" is 115 to 125 mm; the photo says 127 +- 4, and it is the model's number.
    measured = spec["dims"]["short_leg_measured"]
    assert measured["mm"] == pytest.approx(126.9, abs=0.1)
    assert measured["tolerance_mm"] < spec["dims"]["short_leg"]["tolerance_mm"]


def test_the_first_holes_sit_alike_on_both_legs(spec):
    d = spec["dims"]
    tolerance = d["hole_wall_1"]["tolerance_mm"] + d["hole_shelf_1"]["tolerance_mm"]
    assert abs(d["hole_wall_1"]["mm"] - d["hole_shelf_1"]["mm"]) < tolerance


def _plate(points, z0, z1):
    a, b = [(x, y, z0) for x, y in points], [(x, y, z1) for x, y in points]
    tris = []
    for i in range(len(points)):
        j = (i + 1) % len(points)
        tris += [(a[i], a[j], b[j]), (a[i], b[j], b[i])]
    for i in range(1, len(points) - 1):
        tris += [(a[0], a[i + 1], a[i]), (b[0], b[i], b[i + 1])]
    return tris


def bracket_triangles(d: dict) -> list:
    """The bracket's silhouette as examples/shelf_bracket.py builds it: two legs and the strut, without the bend."""
    t, width = d["thickness"], d["width"]
    tris = _box(0, -t, 0, d["long_leg"], 0, width) + _box(0, -d["short_leg_measured"], 0, t, 0, width)
    strut = [(t, -d["strut_wall_top"]), (d["strut_shelf_top"], -t),
             (d["strut_shelf_bottom"], -t), (t, -d["strut_wall_bottom"])]
    return tris + _plate(strut, 0, t)


def test_a_bracket_built_from_the_spec_matches_the_photo(tmp_path, spec):
    mesh = _stl(tmp_path / "bracket.stl", bracket_triangles(specs.model_dims(spec)))
    [result] = check_likeness(mesh, spec, tmp_path / "likeness")
    assert "better_pose" not in result
    assert result["iou"] > 0.88, result
    # The legs stand 20 mm off the table, so the photo is not quite flat: close, not exact.
    assert likeness_advice([result])[0].severity == "warn"
    assert math.isclose(result["model_mm"][1], spec["dims"]["short_leg_measured"]["mm"], abs_tol=0.01)
