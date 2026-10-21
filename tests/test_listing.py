import json
from pathlib import Path

import pytest

from print3d import spec as specs
from print3d.cli import main
from test_likeness import CARD_PX, L_OUTLINE, _l_part, _photo
from test_mcp_server import _call, jobs  # noqa: F401  (fixture)

URL = "https://shop.example/l-bracket"


def _listed(spec: dict) -> dict:
    """The L part as a shop lists it: 40 mm wide, read off its product photo."""
    specs.listing_dim(spec, "width", 40, "Size: 40 x 30 x 15 mm")
    return spec


def test_a_listed_dimension_needs_its_quote():
    spec = specs.load_spec(Path("/nonexistent"))
    with pytest.raises(specs.SpecError, match="Quote the listing"):
        specs.listing_dim(spec, "width", 40, None)


def test_a_listed_dimension_carries_its_rounding():
    spec = _listed(specs.load_spec(Path("/nonexistent")))
    assert spec["dims"]["width"] == {
        "mm": 40, "source": "listing", "tolerance_mm": specs.LISTING_TOLERANCE_MM, "quote": "Size: 40 x 30 x 15 mm",
    }
    specs.listing_dim(spec, "length", 120, "12 cm long", tolerance_mm=5)
    assert spec["dims"]["length"]["tolerance_mm"] == 5


def test_a_listed_dimension_scales_the_product_photo(tmp_path):
    spec = _listed(specs.load_spec(tmp_path))
    photo = _photo(tmp_path / "product.png")
    # The L's bottom edge spans the listed 40 mm: 200 px.
    entry = specs.set_scale(spec, "front", photo, "dim:width", [[300, 650], [500, 650]])
    assert entry["scale"]["mm_per_px"] == pytest.approx(0.2)
    assert entry["scale"]["ref_tolerance_mm"] == specs.LISTING_TOLERANCE_MM
    height = specs.measure_dim(spec, "height", "front", [[300, 500], [300, 650]])
    assert height["mm"] == pytest.approx(30)


def test_the_listings_rounding_widens_what_is_measured_from_it(tmp_path):
    photo = _photo(tmp_path / "product.png")
    card = specs.load_spec(tmp_path)
    specs.set_scale(card, "front", photo, "card", [[100, 100], [100 + CARD_PX, 100]])
    listed = _listed(specs.load_spec(tmp_path))
    specs.set_scale(listed, "front", photo, "dim:width", [[300, 650], [500, 650]])
    points = [[300, 500], [300, 650]]
    by_card = specs.measure_dim(card, "height", "front", points)["tolerance_mm"]
    by_listing = specs.measure_dim(listed, "height", "front", points)["tolerance_mm"]
    # 0.5 mm in 40 mm is 1.25% of the 30 mm height, on top of a shorter reference's picking.
    assert by_listing > by_card + 0.3


def test_only_a_stated_dimension_can_be_a_reference(tmp_path):
    spec = specs.load_spec(tmp_path)
    specs.given_dim(spec, "depth", 15, "assumed", "not shown")
    for ref in ("dim:depth", "dim:missing"):
        with pytest.raises(specs.SpecError, match="given by the user or quoted from the listing"):
            specs.set_scale(spec, "front", tmp_path / "p.png", ref, [[0, 0], [10, 0]])


def test_the_listing_is_recorded(tmp_path):
    spec = specs.load_spec(tmp_path)
    assert specs.set_listing(spec, URL, "L bracket", 3.99, "EUR") == {
        "url": URL, "name": "L bracket", "price": 3.99, "currency": "EUR",
    }
    assert specs.set_listing(spec, URL) == {"url": URL}


def test_listing_from_the_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PRINT3D_JOBS", str(tmp_path))
    photo = _photo(tmp_path / "product.png")
    for argv in (
        ["listing", URL, "--price", "3.99", "--currency", "EUR"],
        ["dim", "width", "--mm", "40", "--source", "listing", "--quote", "Size: 40 x 30 x 15 mm"],
        ["scale", "front", str(photo), "--ref", "dim:width", "--points", "300,650,500,650"],
    ):
        assert main(["measure", "l", *argv]) == 0
    spec = json.loads((tmp_path / "l" / "spec.json").read_text())
    assert spec["listing"]["price"] == 3.99
    assert spec["views"]["front"]["scale"]["mm_per_px"] == pytest.approx(0.2)
    assert main(["measure", "l", "dim", "depth", "--mm", "15", "--source", "listing"]) == 1
    assert "Quote the listing" in capsys.readouterr().err


def test_listing_to_likeness_over_mcp(tmp_path, jobs):  # noqa: F811
    photo = _photo(tmp_path / "product.png")
    mesh = _l_part(tmp_path / "l.stl")
    *_, spec, likeness = _call(
        ("set_listing", {"slug": "l", "url": URL, "name": "L bracket"}),
        ("measure_dim", {"slug": "l", "name": "width", "mm": 40, "source": "listing",
                         "quote": "Size: 40 x 30 x 15 mm"}),
        ("measure_scale", {"slug": "l", "view": "front", "photo": str(photo), "ref": "dim:width",
                           "points": [[300, 650], [500, 650]]}),
        ("measure_outline", {"slug": "l", "view": "front", "points": L_OUTLINE}),
        ("show_spec", {"slug": "l"}),
        ("likeness", {"slug": "l", "mesh": str(mesh)}),
    )
    assert json.loads(spec.content[0].text)["listing"] == {"url": URL, "name": "L bracket"}
    assert json.loads(likeness.content[0].text)["advice"][0]["severity"] == "note"
