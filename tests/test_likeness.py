from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from print3d import spec as specs
from print3d.likeness import check_likeness, likeness_advice
from print3d.photo import grid

# A card 428 px long makes 0.2 mm per pixel. The L below is 40 x 30 mm: a
# 40 x 10 bar on the bed with a 10 x 30 column on its left.
CARD_PX = 428
L_OUTLINE = [[300, 500], [350, 500], [350, 600], [500, 600], [500, 650], [300, 650]]


def _photo(path: Path) -> Path:
    image = Image.new("RGB", (1000, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 100 + CARD_PX, 370], fill="steelblue")
    draw.polygon([tuple(p) for p in L_OUTLINE], fill="black")
    image.save(path)
    return path


def _box(x0, y0, z0, x1, y1, z1):
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return [tri for a, b, d, e in quads for tri in ((c[a], c[b], c[d]), (c[a], c[d], c[e]))]


def _stl(path: Path, triangles) -> Path:
    lines = ["solid t"]
    for tri in triangles:
        lines += ["facet normal 0 0 0", "outer loop", *("vertex %g %g %g" % v for v in tri), "endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid t"]), encoding="ascii")
    return path


def _l_part(path: Path, *, width=40.0, column_at_left=True) -> Path:
    cx = (0.0, 10.0) if column_at_left else (width - 10.0, width)
    return _stl(path, _box(0, 0, 0, width, 15, 10) + _box(cx[0], 0, 0, cx[1], 15, 30))


@pytest.fixture
def spec(tmp_path: Path) -> dict:
    spec = {"views": {}, "dims": {}, "unknowns": []}
    photo = _photo(tmp_path / "photo.png")
    specs.set_scale(spec, "front", photo, "card", [[100, 100], [100 + CARD_PX, 100]])
    specs.set_outline(spec, "front", points=L_OUTLINE)
    return spec


def test_a_card_in_the_photo_sets_the_scale(spec):
    width = specs.measure_dim(spec, "width", "front", [[300, 650], [500, 650]])
    assert width["mm"] == pytest.approx(40.0, abs=0.1)
    assert width["source"] == "measured"
    assert 0 < width["tolerance_mm"] < 2.0


def test_an_assumed_dimension_has_to_say_why(spec):
    with pytest.raises(specs.SpecError):
        specs.given_dim(spec, "depth", 15.0, "assumed", None)
    assert specs.given_dim(spec, "depth", 15.0, "assumed", "not visible")["why"] == "not visible"
    assert specs.model_dims(spec) == {"depth": 15.0}


def test_the_right_model_matches(tmp_path, spec):
    [result] = check_likeness(_l_part(tmp_path / "l.stl"), spec, tmp_path / "likeness")
    assert result["iou"] > 0.95
    assert result["model_mm"] == [40.0, 30.0]
    assert "better_pose" not in result
    assert Path(result["overlay"]).is_file()
    assert likeness_advice([result])[0].severity == "note"


def test_a_mirrored_model_is_told_which_way_to_look(tmp_path, spec):
    [result] = check_likeness(_l_part(tmp_path / "l.stl", column_at_left=False), spec, tmp_path / "out")
    assert result["iou"] < 0.8
    assert result["better_pose"]["look"] == "-y"
    assert result["better_pose"]["up"] == "+z"
    assert likeness_advice([result])[0].severity == "error"


def test_right_shape_wrong_size_names_the_dimension(tmp_path, spec):
    [result] = check_likeness(_l_part(tmp_path / "l.stl", width=48.0), spec, tmp_path / "out")
    [note] = likeness_advice([result])
    assert note.severity == "error"
    assert "width 48.0 mm" in note.fix


def test_no_outline_means_no_check(tmp_path, spec):
    del spec["views"]["front"]["outline"]
    assert check_likeness(_l_part(tmp_path / "l.stl"), spec, tmp_path / "out") == []


def test_grid_zooms_into_a_crop(tmp_path):
    out = grid(_photo(tmp_path / "photo.png"), tmp_path / "grid.png", crop=(280, 480, 520, 670))
    assert out["crop"] == [280, 480, 520, 670]
    assert out["zoom"] > 1
    assert Image.open(out["grid"]).width == round(240 * out["zoom"])
