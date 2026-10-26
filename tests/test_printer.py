import pytest

from print3d.printer import PrinterError, list_printers, load_printer


def test_both_profiles_load():
    voron = load_printer("voron300-sc")
    assert voron.backend == "prusaslicer"
    assert len(voron.tools) == 3 and voron.nozzle_mm == 0.4
    assert voron.bed_mm == (300, 300, 280)
    assert voron.bed_exclude == ((200, 250, 300, 300),)
    assert voron.config_for(None).name == "pla.ini" and voron.config_for("pla").is_file()
    x2d = load_printer("x2d-0.4")
    assert x2d.backend == "bambu" and len(x2d.tools) == 2
    assert x2d.config_for("PLA").name == "filament.json"
    assert {"voron300-sc", "x2d-0.4"} <= set(list_printers())


def test_unknown_printer_and_material_name_the_options():
    with pytest.raises(PrinterError, match="voron300-sc"):
        load_printer("nope")
    with pytest.raises(PrinterError, match="PLA"):
        load_printer("voron300-sc").config_for("ABS")
    with pytest.raises(PrinterError):
        load_printer("../etc")


def test_env_override(monkeypatch):
    assert load_printer().key == "voron300-sc"
    monkeypatch.setenv("PRINT3D_PRINTER", "x2d-0.4")
    assert load_printer().key == "x2d-0.4"
    assert load_printer("voron300-sc").key == "voron300-sc"
