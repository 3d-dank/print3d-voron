import re
import zipfile

import pytest

from conftest import write_cube_stl
from print3d.project_3mf import place, write_3mf
from print3d.slicer import Part, SlicerError

BED = (300.0, 300.0, 280.0)
EXCLUDE = ((200.0, 250.0, 300.0, 300.0),)


def _parts(tmp_path):
    a = write_cube_stl(tmp_path / "a.stl", 20)
    b = write_cube_stl(tmp_path / "b.stl", 10)
    c = write_cube_stl(tmp_path / "c.stl", 30)
    return [
        ("two", [Part("a", a, 1, object="two", settings={"wall_loops": 4, "fancy": 1}),
                 Part("b", b, 2, object="two")]),
        ("one", [Part("c", c, 3)]),
    ]


def test_volumes_extruders_and_settings(tmp_path):
    out = tmp_path / "x.3mf"
    written = write_3mf(_parts(tmp_path), BED, out, EXCLUDE)
    with zipfile.ZipFile(out) as z:
        assert {"3D/3dmodel.model", "Metadata/Slic3r_PE_model.config", "[Content_Types].xml"} <= set(z.namelist())
        config = z.read("Metadata/Slic3r_PE_model.config").decode()
        model = z.read("3D/3dmodel.model").decode()
    volumes = re.findall(r'<volume firstid="(\d+)" lastid="(\d+)">', config)
    assert volumes == [("0", "11"), ("12", "23"), ("0", "11")]
    assert re.findall(r'key="extruder" value="(\d)"', config) == ["1", "1", "2", "3", "3"]
    assert 'key="perimeters" value="4"' in config and 'key="fancy" value="1"' in config
    assert written.untranslated == ("fancy",)
    assert model.count("<triangle ") == 36 and model.count("<item ") == 2


def test_placement_inside_bed_and_clear_of_exclude(tmp_path):
    corners = place([(100, 100), (100, 100), (100, 100)], BED, EXCLUDE)
    for (x, y) in corners:
        assert 0 <= x and x + 100 <= BED[0] and 0 <= y and y + 100 <= BED[1]
        assert not (x < 300 and 200 < x + 100 and y < 300 and 250 < y + 100)


def test_too_big_raises(tmp_path):
    big = write_cube_stl(tmp_path / "big.stl", 290)
    with pytest.raises(SlicerError):
        write_3mf([("big", [Part("big", big, 1)])], BED, tmp_path / "x.3mf", EXCLUDE)
    with pytest.raises(SlicerError):
        place([(100, 100)], (300, 300, 280), ((0, 0, 300, 300),))
