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

## Phase 1 plan (approved to start 2026-10-26)

Printer preset decided: `Voron_v2_300_afterburner 0.4 Perfect` (klipper, PRINT_START,
thumbnails 64x64 + 400x300, 280 mm Z, bed notched at x200-300 y250-300).

### Profile: `src/print3d/profiles/voron300-sc/`
- `printer.toml` as above, plus `bed_exclude = [[200, 250, 300, 300]]` (x0,y0,x1,y1) and
  `materials = { PLA = "pla.ini" }` for now (ABS/PETG are phase 2).
- `pla.ini`: built by `scripts/make_prusa_profile.py` (committed, rerunnable):
  `PrusaSlicer --load <printer> --load <print> --load <filament> --save tmp.ini`, then expand to
  N extruders (`len(tools)`), the cleaned-up version of phase0/expand.py: per-extruder numeric
  vectors comma-joined, string vectors `;`-joined, `machine_max_*` left at 2 values,
  `wipe_tower = 1`, `use_relative_e_distances = 1`, `layer_gcode = G92 E0`.
  Sources: printer above, print `0.2mm 0.4nozzle V3 - ABS Voron 300`, filament
  `Basic PLA @VORON - EM100`. Strip `print_host`, `printhost_*`, `physical_printer*` keys.
  Write `provenance.txt` (source preset names, PrusaSlicer version, date).
- `x2d-0.4/printer.toml`: `backend = "bambu"`, `bed_mm = [256, 256, 260]`, 2 tools 0.4,
  `materials = { PLA = "filament.json" }`.

### Interfaces
- `printer.py`: `Tool(index, klipper, nozzle_mm, head)`; `Printer(key, name, dir, backend,
  bed_mm, bed_exclude, tools, default_material, materials)` with `nozzle_mm`,
  `config_for(material|None) -> Path`. `load_printer(name|None)`: name, else
  `$PRINT3D_PRINTER`, else `voron300-sc`; name passes `safe_name`. `list_printers()`.
  `PrinterError` names the known printers/materials.
- `slicer.py`: `Part(name, stl, tool, plate=1, object=None, settings={})` (tool is the
  1-based extruder; parts sharing object+plate are volumes of one object).
  `SliceJob(printer, parts, out_dir, slug, colours, material=None)` (`colours[i]` is the
  colour name for tool i+1). `PlateResult(index, gcode, png, review_3mf, grams_by_tool,
  weight_g)`. `SliceResult(returncode, plates, output, output_size_bytes, review_3mf, log)`.
  `Slicer` protocol: `plan(job) -> dict` (no binary needed), `slice(job, timeout_s=180)
  -> SliceResult`. `slicer_for(printer)` picks by `printer.backend`.
- `bambu_slicer.py`: `BambuStudio` wraps today's studio.py flow unchanged (SliceRequest,
  assemble_list, job_filaments, run_slice, inspect_project, extract_plate_png,
  slice_info grams). It writes each plate's G-code out to `slice/<slug>_plate_N.gcode`.
- `prusa_slicer.py`: `find_prusaslicer()` (`PRUSASLICER_BIN`, then the pinned app path).
  `PrusaSlicer.slice`: per plate, `project_3mf.write_3mf` -> raw 3MF; write
  `slice/overrides.ini` (`extruder_colour`/`filament_colour` per tool from `colour_hex`);
  `--load <material ini> --load overrides.ini --export-3mf -o <review>.3mf raw.3mf`;
  then `--load ... --load ... --export-gcode -o <slug>[_plate_N].gcode <review>.3mf`.
  Review file `<slug>.3mf` for one plate, `<slug>_plate_N.3mf` for several. PNG = largest
  thumbnail. Stderr tail in errors, like studio.py.
- `project_3mf.py`: `write_3mf(objects, bed, out) -> Path`, our own PrusaSlicer-format 3MF
  (zipfile + trimesh): one `<object>` per object, its parts' meshes concatenated, and
  `Metadata/Slic3r_PE_model.config` with one `<volume firstid lastid>` per part carrying
  `extruder`, `name`, `volume_type=ModelPart`, identity `matrix`; object-level per-part
  settings translated by `SETTINGS_MAP` (`wall_loops->perimeters`,
  `sparse_infill_density->fill_density`, `top_shell_layers->top_solid_layers`,
  `bottom_shell_layers->bottom_solid_layers`; unknown keys passed through and listed in the
  result as `untranslated`). Placement: each object dropped to z=0, shelf-packed with 5 mm
  gaps, group centred on the bed; raise `SliceError` if any footprint leaves the bed rect or
  touches a `bed_exclude` rect. Include `Metadata/Slic3r_PE.config` only if PrusaSlicer
  needs it to load (check phase0/m3 for the minimum it wrote).
- `gcode_stats.py`: `is_prusaslicer(gcode)`, `parse_prusaslicer(gcode) -> GcodeStats(
  estimated_time, estimated_minutes, filament_g, grams_by_tool {1: g, ...}, layer_count,
  thumbnail_png)`. Formats (verified, 2.9.6): `; filament used [g] = 4.45, 2.37, 0.00`,
  `; total filament used [g] = 6.82`, `; estimated printing time (normal mode) = 31m 12s`,
  layers = count of `;LAYER_CHANGE`, thumbnails `; thumbnail begin WxH LEN` ... `; thumbnail
  end` (base64 lines prefixed `; `). Pick the largest.
- `printability.analyze_gcode(gcode, plate=1)`: today's analyze_slice body. Header stats from
  gcode_stats when `is_prusaslicer`, else the Bambu header regexes. With no
  `CONFIG_BLOCK_END`, the whole text is the body. `analyze_slice(project, plate)` stays as a
  wrapper (Bambu tests).
- `paths.py`: `default_profiles_dir()` becomes `load_printer().dir` (keep the function).
- pipeline: `run_job(..., printer: str|None = None)`; `_run_job`/`_run_parts` build Parts
  (single mesh = one Part, tool 1) and call `slicer_for(printer).plan/slice`; the per-plate
  loop reads `PlateResult`. Profile-missing check moves to the backend (bambu keeps the
  `flatten` hint). `NOZZLES` -> `len(printer.tools)`; for `prusaslicer`, more colours than
  tools is an `error` ("N colours, M tools"). `require_printable`/`check_mesh` take
  `bed_mm=printer.bed_mm`. Report keys stay (`open_in_studio`, `slice_result`, `plates`,
  `plate_png`, `inspection` = `{"plates": [...], "path": review_3mf}`); `next_step` text names
  the printer's slicer ("Open the .3mf in PrusaSlicer ...").
- cli/mcp: `--printer` on run/plan-like commands; `printers` command lists them. Text
  changes elsewhere (handoff, skill, Bambu strings) wait for phase 2+ unless a test needs them.

### Tests (all offline unless marked)
- printer: loads both profiles; unknown printer/material errors; env override.
- project_3mf: two objects, one with two parts on tools 1 and 2 -> zip has right volume
  ranges/extruders; placement inside bed and clear of exclude; too big -> SliceError.
- gcode_stats: fixture trimmed from a real 2.9.6 G-code (footer + one small thumbnail).
- analyze_gcode on that fixture: layer_count, grams, minutes.
- prusa plan: commands contain both `--load`s, `--export-3mf`, `--export-gcode`, no binary.
- test_pipeline_state: patch the new seam (`pipeline.slicer_for`) with the same assertions.
- `@pytest.mark.skipif(no PrusaSlicer)` integration: slice a 2-part, 2-tool cube+cylinder
  through `PrusaSlicer.slice`; G-code has `T0` and `T1`, grams_by_tool has 2 non-zero.
- All existing tests stay green except test_studio_it (needs Bambu Studio).

### Constraints
- Never send anything to Moonraker; no API keys in the repo (strip host keys from inis).
- Do not delete studio.py, flatten.py, repair_3mf.py; x2d-0.4 must still plan correctly.
- Copy Jeff's presets; never write into `~/Library/Application Support/PrusaSlicer`.

### Order
1 printer.py + both printer.toml + make_prusa_profile.py/pla.ini. 2 gcode_stats + analyze_gcode.
3 project_3mf. 4 slicer.py + both backends. 5 pipeline/cli. 6 integration test. 7 Gate run:
`python -m print3d run "nameplate that says VORON" --script examples/nameplate.py`, open
`<slug>.3mf` in PrusaSlicer for Jeff.
