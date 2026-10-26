# Port plan: Bambu Studio / X2D -> PrusaSlicer / Klipper

Upstream audited at 28 commits (the brief counted 21), 7.5k lines of Python incl. tests.

## Bambu / X2D assumptions found

| # | Where | Assumption |
|---|-------|------------|
| 1 | paths.py `default_profiles_dir` | Hard-codes `profiles/x2d-0.4` |
| 2 | pipeline.py `_run_job` | Requires machine/process/filament.json; error tells you to run `flatten` |
| 3 | studio.py | Bambu CLI flags: `--datadir`, `--orient`, `--arrange`, `--ensure-on-bed`, `--curr-bed-type "Textured PEI Plate"`, `--load-assemble-list`; output is `.gcode.3mf` plus a review `.3mf` |
| 4 | studio.py `assemble_list` | Multi-part and multi-plate jobs go through Bambu's JSON assemble list |
| 5 | project.py | Reads `Metadata/plate_N.gcode`, `slice_info.config`, `plate_N.png` out of the Bambu 3MF |
| 6 | pipeline.py `_run_parts` | Per-plate grams come from `slice_info.config` |
| 7 | printability.py | `WEIGHT_RE` matches Bambu's `total filament weight [g]`; G-code read from the 3MF; assumes `enable_support = 0`; 0.4 mm nozzle floor hard-coded; advice says "in Studio" |
| 8 | dfm.py | `X2D_BED_MM = (256, 256, 260)`; message mentions `--ensure-on-bed` |
| 9 | filaments.py | `NOZZLES = 2`; Bambu PLA Basic colour names; colour = a copy of filament.json |
| 10 | fits.py | One global fits.json; defaults described as 0.4 mm PLA |
| 11 | handoff.py | Cost from `filament.json["filament_cost"][0]`; subtitle hard-codes "Bambu Lab X2D, 0.4 mm nozzle, 0.20 mm layers, Bambu PLA Basic, textured PEI, supports off"; "Open the .3mf in Bambu Studio" |
| 12 | cli.py | `flatten` and `plan` commands, `find_studio`, `stops_at: "review in Bambu Studio"`, prog description |
| 13 | mcp_server.py, `__init__`, skill/, skills/ | Instruction text names Bambu Studio and X2D |
| 14 | tests | test_studio_it.py and test_flatten.py are Bambu-only |

## Profile layer (proposal, not yet built)

```
src/print3d/profiles/voron300-sc/
  printer.toml        # manifest (below)
  abs.ini petg.ini pla.ini   # PrusaSlicer File > Export > Export Config, one per material
```

`printer.toml`:
```toml
name = "Voron 2.4 300 StealthChanger"
backend = "prusaslicer"          # "bambu" for x2d-0.4, so upstream keeps working
bed_mm = [300, 300, 280]         # REAL printable area after docks; measure in phase 4
default_material = "PLA"
[[tools]]                        # PrusaSlicer extruder N  ->  Klipper T(N-1)
klipper = "T0"; nozzle_mm = 0.4; head = "Anthead"
[[tools]]
klipper = "T1"; nozzle_mm = 0.4; head = "Galileo 2"
[[tools]]
klipper = "T2"; nozzle_mm = 0.4; head = "Rapido 2F"
[materials]
ABS = "abs.ini"; PETG = "petg.ini"; PLA = "pla.ini"
[moonraker]
url = "http://HOST:7125"         # key from MOONRAKER_API_KEY, never in this file
```

New and changed interfaces:
- `printer.py`: `load_printer(name) -> Printer` with `bed_mm`, `tools`, `nozzle_mm`,
  `config_for(material) -> Path`, `backend`. It replaces `default_profiles_dir()` everywhere.
- `slicer.py`: `Slicer` protocol, `slice(printer, parts: list[Part], out_dir) -> SliceResult`.
  `Part = (mesh, tool, material, colour)`. `SliceResult` has `gcode`, `project_3mf` (for
  review in PrusaSlicer), `metrics` (minutes, grams per tool, layers, thumbnail png).
  Two implementations: `PrusaSlicer` (new) and `BambuStudio` (today's studio.py, moved, not
  deleted).
- `project_3mf.py`: build one 3MF from the parts with `--merge --export-3mf`, then set
  `<metadata type="object" key="extruder" value="N"/>` per object in
  `Metadata/Slic3r_PE_model.config`.
- `gcode_stats.py`: parse PrusaSlicer footer comments (`estimated printing time (normal
  mode)`, `filament used [g]` per tool, `;LAYER_CHANGE` count, `; thumbnail begin` base64).
  `project.py` and `printability.py` take metrics from here instead of from the Bambu 3MF.
- `dfm.check_mesh(bed_mm=printer.bed_mm)`; `filaments` takes its tool count from
  `len(printer.tools)`; `fits.json` keyed `printer/nozzle/material`.

**Decided (2026-10-26):** keep studio.py, flatten.py and repair_3mf.py behind
`backend = "bambu"` (x2d-0.4 stays a working profile) instead of deleting them, so the
printer layer can go upstream as a PR.

Plates: PrusaSlicer writes one G-code per bed, so a multi-plate job slices once per plate
(PrusaSlicer 2.9 has multiple beds in the GUI; using that from the CLI is not verified).

## Phases and gates
0. Clone, unit tests, headless PrusaSlicer, two-tool slice with Jeff's presets. **Gate:** both
   tools appear in the G-code.
1. Slicer interface + PrusaSlicer backend + 3MF writer + G-code stats. **Gate:**
   examples/nameplate.py slices clean and looks right in PrusaSlicer's preview.
2. ABS/PETG/PLA configs + per-printer/material fits. **Gate:** coupon results per material.
3. moonraker.py upload with `print=false`. **Gate:** job in Mainsail's file list, not started.
4. StealthChanger start/tool-change G-code, T0-T2 map. **Gate:** a two-colour inlaid box.
5. Voron 350 and MK3S profiles.
