import json

import anyio
import pytest
from mcp import Client

from print3d.mcp_server import server
from test_likeness import CARD_PX, L_OUTLINE, _l_part, _photo


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT3D_JOBS", str(tmp_path / "jobs"))
    return tmp_path / "jobs"


def _call(*calls):
    async def run():
        async with Client(server) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return anyio.run(run)


def test_every_cli_step_is_a_tool():
    async def names():
        async with Client(server) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert {"guide", "make", "grid", "measure_scale", "measure_dim", "measure_outline",
            "add_unknown", "set_listing", "show_spec", "likeness", "check"} <= anyio.run(names)


def test_guide_serves_the_skill():
    photo, listing = _call(("guide", {"topic": "from-photo"}), ("guide", {"topic": "from-listing"}))
    assert "evidence" in photo.content[0].text
    assert "dim:<name>" in listing.content[0].text


def test_grid_comes_back_as_an_image(tmp_path, jobs):
    photo = _photo(tmp_path / "photo.png")
    [result] = _call(("grid", {"photo": str(photo), "crop": [280, 480, 520, 670]}))
    assert [c.type for c in result.content] == ["text", "image"]
    assert json.loads(result.content[0].text)["crop"] == [280, 480, 520, 670]


def test_photo_to_likeness_over_mcp(tmp_path, jobs):
    photo = _photo(tmp_path / "photo.png")
    mesh = _l_part(tmp_path / "l.stl")
    *_, spec, likeness = _call(
        ("measure_scale", {"slug": "l", "view": "front", "photo": str(photo), "ref": "card",
                           "points": [[100, 100], [100 + CARD_PX, 100]]}),
        ("measure_dim", {"slug": "l", "name": "width", "view": "front", "points": [[300, 650], [500, 650]]}),
        ("measure_dim", {"slug": "l", "name": "depth", "mm": 15, "source": "assumed", "why": "not shown"}),
        ("measure_outline", {"slug": "l", "view": "front", "points": L_OUTLINE}),
        ("show_spec", {"slug": "l"}),
        ("likeness", {"slug": "l", "mesh": str(mesh)}),
    )
    assert set(json.loads(spec.content[0].text)["dims"]) == {"width", "depth"}
    assert (jobs / "l" / "spec.json").is_file()
    assert json.loads(likeness.content[0].text)["advice"][0]["severity"] == "note"
    assert likeness.content[1].type == "image"


def test_a_bad_call_is_an_error_not_a_crash(jobs):
    [result] = _call(("measure_dim", {"slug": "l", "name": "width", "view": "front",
                                       "points": [[0, 0], [1, 1]]}))
    assert result.is_error
    assert "no scale yet" in result.content[0].text
