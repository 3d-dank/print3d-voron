"""Build a per-material PrusaSlicer config for an N-tool printer from Jeff's live presets.

    uv run python scripts/make_prusa_profile.py            # voron300-sc, PLA

PrusaSlicer merges printer + print + filament presets into one config; this then repeats
every per-extruder setting once per tool. The live presets are only read.
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print3d.printer import load_printer  # noqa: E402
from print3d.prusa_slicer import find_prusaslicer  # noqa: E402

PRESETS = Path.home() / "Library" / "Application Support" / "PrusaSlicer"
DEFAULTS = {
    "printer": "Voron_v2_300_afterburner 0.4 Perfect",
    "print": "0.2mm 0.4nozzle V3 - ABS Voron 300",
    "filament": "Basic PLA @VORON - EM100",
}
# Per-extruder numeric settings: one value per tool, comma-joined.
NUMERIC = {
    "nozzle_diameter", "extruder_offset", "retract_length", "retract_lift", "retract_lift_above",
    "retract_lift_below", "retract_speed", "deretract_speed", "retract_restart_extra",
    "retract_before_travel", "retract_layer_change", "wipe", "retract_before_wipe",
    "retract_length_toolchange", "retract_restart_extra_toolchange", "travel_max_lift",
    "travel_slope", "travel_ramping_lift", "travel_lift_before_obstacle", "min_layer_height",
    "max_layer_height", "bed_temperature", "first_layer_bed_temperature",
    "first_layer_temperature", "temperature", "bridge_fan_speed", "cooling",
    "disable_fan_first_layers", "fan_always_on", "fan_below_layer_time", "full_fan_speed_layer",
    "max_fan_speed", "min_fan_speed", "min_print_speed", "slowdown_below_layer_time",
    "extrusion_multiplier", "chamber_temperature", "chamber_minimal_temperature",
    "idle_temperature",
}
# Per-extruder string settings: one value per tool, `;`-joined.
STRINGS = {
    "extruder_colour", "filament_colour", "filament_settings_id", "filament_vendor",
    "filament_type", "filament_notes", "start_filament_gcode", "end_filament_gcode",
    "filament_ramming_parameters",
}
# filament_* settings PrusaSlicer reads as a single value.
FILAMENT_SCALAR = {
    "filament_shrink", "filament_shrinkage_compensation_xy", "filament_shrinkage_compensation_z",
    "filament_infill_max_speed",
}
STRIP = re.compile(r"^(print_host|printhost_\w+|physical_printer\w*)\s*=")
LINE = re.compile(r"^(\w+) = (.*)$")


def expand(lines: list[str], tools: int, ids: dict[str, str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.startswith("#") or STRIP.match(line):
            continue
        match = LINE.match(line.rstrip("\n"))
        if not match:
            out.append(line)
            continue
        key, value = match.groups()
        if key == "wipe_tower" or key == "use_relative_e_distances":
            value = "1"
        elif key == "layer_gcode":
            value = "G92 E0"
        elif key in ids:
            value = ";".join([ids[key]] * tools) if key == "filament_settings_id" else ids[key]
        elif key in STRINGS:
            value = ";".join([value] * tools)
        elif key in NUMERIC or (key.startswith("filament_") and key not in FILAMENT_SCALAR):
            value = ",".join([value] * tools)
        out.append(f"{key} = {value}\n")
    return out


def build(printer_key: str, material: str, names: dict[str, str]) -> Path:
    printer = load_printer(printer_key)
    target = printer.config_for(material)
    command = [str(find_prusaslicer())]
    for kind in ("printer", "print", "filament"):
        source = PRESETS / kind / f"{names[kind]}.ini"
        if not source.is_file():
            raise SystemExit(f"missing preset: {source}")
        command += ["--load", str(source)]
    with tempfile.TemporaryDirectory() as tmp:
        merged = Path(tmp) / "merged.ini"
        subprocess.run([*command, "--save", str(merged)], check=True, capture_output=True, text=True)
        lines = merged.read_text(encoding="utf-8").splitlines(keepends=True)
    ids = {
        "print_settings_id": names["print"],
        "printer_settings_id": names["printer"],
        "filament_settings_id": names["filament"],
    }
    header = f"# print3d {printer.key} {material}: merged and expanded to {len(printer.tools)} tools by scripts/make_prusa_profile.py\n"
    target.write_text(header + "".join(expand(lines, len(printer.tools), ids)), encoding="utf-8")
    version = subprocess.run([str(find_prusaslicer()), "--help"], capture_output=True, text=True).stdout
    version = (re.search(r"PrusaSlicer-([\d.]+)", version) or [None, "unknown"])[1]
    (printer.dir / "provenance.txt").write_text(
        "PrusaSlicer presets merged into the per-material configs in this folder.\n\n"
        f"PrusaSlicer version: {version}\n"
        f"Printer preset: {names['printer']}\n"
        f"Print preset: {names['print']}\n"
        f"Filament preset ({material}): {names['filament']}\n"
        f"Tools: {len(printer.tools)}\n"
        f"Generated: {datetime.date.today().isoformat()}\n"
        "Host and physical-printer keys are stripped.\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--printer", default="voron300-sc")
    parser.add_argument("--material", default="PLA")
    for kind, default in DEFAULTS.items():
        parser.add_argument(f"--{kind}-preset", default=default)
    args = parser.parse_args()
    names = {kind: getattr(args, f"{kind}_preset") for kind in DEFAULTS}
    print(build(args.printer, args.material, names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
