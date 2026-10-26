from pathlib import Path

from print3d.gcode_stats import is_prusaslicer, minutes, parse_prusaslicer
from print3d.printability import analyze_gcode

GCODE = (Path(__file__).parent / "fixtures" / "prusa_two_tool.gcode").read_text()


def test_parse_prusaslicer_footer():
    assert is_prusaslicer(GCODE)
    stats = parse_prusaslicer(GCODE)
    assert stats.grams_by_tool == {1: 4.45, 2: 2.37, 3: 0.0}
    assert stats.filament_g == 6.82
    assert stats.estimated_time == "31m 12s" and stats.estimated_minutes == 31.2
    assert stats.layer_count == 3
    assert stats.thumbnail_png and stats.thumbnail_png.startswith(b"\x89PNG")
    # the larger of the two thumbnails (8x6)
    assert stats.thumbnail_png[16:24] == (8).to_bytes(4, "big") + (6).to_bytes(4, "big")


def test_minutes_with_days():
    assert minutes("1d 2h 3m 30s") == 1563.5


def test_analyze_gcode_on_prusaslicer_output():
    result = analyze_gcode(GCODE)
    assert result["layer_count"] == 3
    assert result["filament_g"] == 6.82
    assert result["estimated_minutes"] == 31.2
    assert result["printed_layers"] >= 1


def test_analyze_gcode_without_config_block_uses_whole_text():
    result = analyze_gcode("G1 Z0.2\nG1 X1 Y1 E1\nG1 Z0.4\nG1 X2 Y2 E1\n")
    assert result["printed_layers"] == 2 and result["filament_g"] is None
