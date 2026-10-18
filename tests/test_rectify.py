from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from print3d import spec as specs
from print3d.photo import RECTIFY_MARGIN, RECTIFY_PX_PER_MM, _homography, meet, rectify

# A 40 x 20 mm face drawn square-on at 10 px/mm, with a marker at (30, 5) mm.
FACE_MM = (40.0, 20.0)
MARKER_MM = (30.0, 5.0)
# Where the face's corners land once photographed at an angle.
QUAD = [(180.0, 140.0), (610.0, 90.0), (650.0, 330.0), (130.0, 300.0)]


def _angled_photo(path: Path) -> Path:
    flat = Image.new("RGB", (400, 200), "lightgrey")
    draw = ImageDraw.Draw(flat)
    mx, my = MARKER_MM[0] * 10, MARKER_MM[1] * 10
    draw.ellipse([mx - 15, my - 15, mx + 15, my + 15], fill="black")
    src = [(0, 0), (400, 0), (400, 200), (0, 200)]
    photo = flat.transform((800, 450), Image.Transform.PERSPECTIVE, _homography(QUAD, src),
                           Image.Resampling.BICUBIC, fillcolor="white")
    photo.save(path)
    return path


def _dark_centroid(image: Image.Image) -> tuple[float, float]:
    grey = image.convert("L")
    px = grey.load()
    dark = [(x, y) for x in range(grey.width) for y in range(grey.height) if px[x, y] < 60]
    return sum(x for x, _ in dark) / len(dark), sum(y for _, y in dark) / len(dark)


def test_meet_crosses_two_edges():
    assert meet((0, 0), (10, 10), (0, 10), (10, 0)) == (5.0, 5.0)
    with pytest.raises(ValueError):
        meet((0, 0), (10, 0), (0, 5), (10, 5))


def test_rectify_puts_the_face_back_square_on(tmp_path):
    out = tmp_path / "flat.png"
    rectify(_angled_photo(tmp_path / "photo.jpg"), QUAD, FACE_MM, out)
    margin = RECTIFY_MARGIN * max(FACE_MM) * RECTIFY_PX_PER_MM
    x, y = _dark_centroid(Image.open(out))
    assert x == pytest.approx(margin + MARKER_MM[0] * RECTIFY_PX_PER_MM, abs=2)
    assert y == pytest.approx(margin + MARKER_MM[1] * RECTIFY_PX_PER_MM, abs=2)


def test_a_rectified_view_measures_in_millimetres(tmp_path):
    spec = {"views": {}, "dims": {}, "unknowns": []}
    view = specs.rectify_view(spec, "top", _angled_photo(tmp_path / "photo.jpg"), [list(c) for c in QUAD],
                              FACE_MM, tmp_path / "views" / "top.png")
    assert view["photo"] == str((tmp_path / "views" / "top.png").resolve())
    assert view["scale"]["mm_per_px"] == pytest.approx(1 / RECTIFY_PX_PER_MM)
    (x0, y0), (x1, _) = view["scale"]["points"]
    width = specs.measure_dim(spec, "width", "top", [[x0, y0], [x1, y0]])
    assert width["mm"] == pytest.approx(FACE_MM[0])
