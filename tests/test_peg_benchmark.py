"""A clothes peg from a museum photo, scored against the museum's catalogue.

The photo is square-on with a cm ruler beside the peg, so the scale comes from
the ruler, not from the object. Every point was read off a grid crop, as the
agent would, and replays here into a spec. The catalogue gives length 115 mm
and diameter 20 mm; both are whole multiples of 5 mm, so it is scored to that.
"""

import json
import math
from pathlib import Path

import pytest

from print3d import spec as specs
from print3d.likeness import check_likeness, likeness_advice
from test_likeness import _box, _stl

FIXTURES = Path(__file__).parent / "fixtures"
BENCH = json.loads((FIXTURES / "peg.json").read_text())
CATALOGUE = BENCH["catalogue_mm"]
ROUNDING_MM = 2.5


def build_spec(job_dir: Path) -> dict:
    """The spec an agent builds from the photo, replayed from the recorded points."""
    spec = specs.load_spec(job_dir)
    ruler = BENCH["ruler"]
    # Printed standing on its knob: the peg's axis is z, and the slot opens along x.
    specs.set_scale(spec, "side", FIXTURES / "peg.jpg", str(ruler["ref_mm"]), ruler["points"], look="-y", up="+x")
    for name, points in BENCH["measured"].items():
        specs.measure_dim(spec, name, "side", points)
    specs.given_dim(spec, "chamfer", 0.8, "assumed", "the ends are rounded, too softly to measure at 0.15 mm/px")
    specs.add_unknown(spec, "The spring is wrapped steel wire: it is not printed.")
    specs.add_unknown(spec, "The slot is taken to run through the whole peg, as the photo shows; its far side is hidden.")
    specs.set_outline(spec, "side", points=BENCH["outline"])
    specs.save_spec(job_dir, spec)
    return spec


@pytest.fixture(scope="module")
def spec(tmp_path_factory) -> dict:
    return build_spec(tmp_path_factory.mktemp("peg"))


def test_scale_comes_from_the_ruler(spec):
    assert spec["views"]["side"]["scale"]["mm_per_px"] == pytest.approx(140 / 905)


def test_length_matches_the_catalogue(spec):
    assert abs(spec["dims"]["length"]["mm"] - CATALOGUE["length"]) <= ROUNDING_MM
    assert spec["dims"]["length"]["mm"] == pytest.approx(114.9, abs=0.1)


def test_diameter_matches_the_catalogue(spec):
    # The catalogue's diameter is the widest point: the spring wrapped round the wood.
    assert abs(spec["dims"]["spring_diameter"]["mm"] - CATALOGUE["diameter"]) <= ROUNDING_MM


def test_the_slot_runs_about_half_the_peg(spec):
    # The catalogue: "longitudinal cut to approximately half way from one end".
    ratio = spec["dims"]["slot_length"]["mm"] / spec["dims"]["length"]["mm"]
    assert 0.45 < ratio < 0.55


def test_every_dimension_says_where_it_came_from(spec):
    sources = {dim["source"] for dim in spec["dims"].values()}
    assert sources == {"measured", "assumed"}
    assert len(spec["unknowns"]) == 2


def profile(d: dict) -> list[tuple[float, float]]:
    """(z, radius) along the peg's axis, from the knob up, as examples/dolly_peg.py turns it."""
    knob, neck, body = d["knob_diameter"] / 2, d["neck_diameter"] / 2, d["body_diameter"] / 2
    return [(0, knob), (d["knob_length"], knob), (d["knob_length"], neck), (d["neck_at"], neck),
            (d["body_at"], body), (d["length"], body)]


def _frustum(z0, r0, z1, r1, sides=48):
    ring = lambda z, r: [(r * math.cos(2 * math.pi * i / sides), r * math.sin(2 * math.pi * i / sides), z)
                         for i in range(sides)]
    a, b = ring(z0, r0), ring(z1, r1)
    tris = []
    for i in range(sides):
        j = (i + 1) % sides
        tris += [(a[i], a[j], b[j]), (a[i], b[j], b[i])]
        tris += [((0, 0, z0), a[j], a[i]), ((0, 0, z1), b[i], b[j])]
    return tris


def peg_triangles(d: dict) -> list:
    """The peg's silhouette-bearing solids: a turned body, and two prongs either side of the slot."""
    slot_start = d["length"] - d["slot_length"]
    tris = []
    points = [(z, r) for z, r in profile(d) if z <= slot_start] + [(slot_start, d["body_diameter"] / 2)]
    for (z0, r0), (z1, r1) in zip(points, points[1:]):
        if z1 > z0:
            tris += _frustum(z0, r0, z1, r1)
    r, half = d["body_diameter"] / 2, d["slot_width"] / 2
    tris += _box(half, -r, slot_start, r, r, d["length"])
    tris += _box(-r, -r, slot_start, -half, r, d["length"])
    return tris


def test_a_peg_built_from_the_spec_matches_the_photo(tmp_path, spec):
    mesh = _stl(tmp_path / "peg.stl", peg_triangles(specs.model_dims(spec)))
    [result] = check_likeness(mesh, spec, tmp_path / "likeness")
    assert "better_pose" not in result
    assert result["iou"] > 0.89, result
    assert result["tilt_deg"] != 0  # the museum photo is not quite level
    assert likeness_advice([result])[0].severity == "note"
