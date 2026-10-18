# print3d

Turn an idea, or a photo of an object, into a Bambu Studio project for a
**Bambu Lab X2D (0.4 mm nozzle)**.

You (or an agent) write a Blender script that builds the part. `print3d` runs it,
checks the mesh, slices it with Bambu Studio, and tells you what to fix. Repeat
until the checks pass, then open the `.3mf` in Studio and print from there.

```
idea -> Blender script -> mesh -> checks -> slice -> .3mf -> print from Studio
             ^                      |
             +---- fix the script --+
```

Nothing here talks to the printer.

## Install

Needs [Blender](https://www.blender.org/download/) 4.2+,
[Bambu Studio](https://bambulab.com/en/download/studio) and
[uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/mfranzon/print3d
print3d setup
```

`setup` finds Claude Code, Codex, Cursor and Gemini CLI on this machine, shows
what it will change, and on your yes registers the print3d MCP server with each
(Claude Code also gets the `/print3d` skill). Edited config files are backed up
beside themselves. Restart your agent afterwards. `--dry-run` shows the plan
without changing anything; `--agent codex` limits it to one agent.

`print3d status` shows where Blender and Studio were found. On macOS this is
automatic; otherwise set `BLENDER_BIN` and `BAMBU_STUDIO_BIN`. Jobs go to
`~/print3d/jobs`, or `$PRINT3D_JOBS`.

To update, run `uv tool upgrade print3d`, then `print3d setup` again.

## Use

```bash
print3d make "a 40mm nameplate that says MARCO" --script examples/nameplate.py
```

This models, checks, slices and prints a JSON report. It exits 1 if any check
fails. Without `--script`, it writes a starter `jobs/<slug>/model.py` for you to
fill in and run again.

Output lands in `jobs/<slug>/`. Open `slice/<slug>.3mf` in Studio. The
`.gcode.3mf` next to it is the sliced job and won't open in the Prepare tab.

Other commands:

| Command | What it does |
| --- | --- |
| `model script.py out.stl` | Run a Blender script to an STL |
| `slice model.stl` | Check and slice an existing mesh |
| `check model.stl` | Printability checks only |
| `inspect job.gcode.3mf` | Time, filament and layers of a sliced job |
| `grid photo.jpg` | Pixel coordinates over a photo, or a zoomed `--crop` |
| `measure <slug> ...` | Record scale (or `rectify` an angled face), dimensions, outlines and unknowns in `spec.json` |
| `meet edge edge` | The corner where two edges cross, when it is hidden |
| `likeness <slug>` | Compare the mesh with the photographed outlines |
| `plan model.stl out.gcode.3mf` | Show the Studio command without running it |
| `flatten` | Rebuild the X2D presets in `src/print3d/profiles/x2d-0.4/` |
| `setup` | Register print3d with your agents |
| `mcp` | Run the MCP server on stdio (agents launch this) |

## Writing a model script

Plain bpy that builds geometry. `examples/nameplate.py` is the reference.

- 1 Blender unit = 1 mm.
- `params` holds the brief: `prompt`, `slug`, `text`, `intent`, `size_mm`,
  `color`, `material`.
- Leave the part as mesh objects. `print3d` joins them, cleans the mesh, centres
  it and puts it on the bed.
- Orientation is up to you. Studio's auto-orient is off, so the part prints the
  way you model it.

More recipes and gotchas: `src/print3d/skill/references/modelling.md`.

## From a photo

Photograph the object square-on, from a distance, next to something of known
size: a bank card, a coin, an A4 sheet, a ruler. `print3d` turns the photo into
measurements you can trace back, and checks that the model looks like it.

```bash
print3d grid knob.jpg --crop 120,340,260,420     # read exact pixels off a zoomed crop
print3d measure knob scale front knob.jpg --ref card --points 131,352,559,352
print3d measure knob dim diameter --view front --points 610,400,790,400
print3d measure knob dim bore --mm 6 --source user
print3d measure knob outline front --points 610,300,790,300,790,520,610,520
print3d make "knob"                               # the model reads params["dims"]
```

Each dimension in `jobs/<slug>/spec.json` records where it came from (measured,
given by you, or assumed with a reason) and, when measured, the pixels, the
reference and a tolerance. Whatever no photo shows is listed as an unknown.

Every outlined view adds a **likeness** check to the run. The STL is projected
along that view, scaled to the photo, and laid over it. If the shape or size
is wrong, or the part is turned or mirrored, the run fails just like it does for
an overhang. `jobs/<slug>/likeness/<view>.png` shows the difference: red is in
the photo but missing from the model, blue is in the model but not in the photo.

Most photos are taken at an angle. `measure rectify` takes the four corners of
a flat face of known size (the object's own top, a card it lies on) and warps
the photo so that face is seen square-on; every later point for that view is
read off the rectified image. When a corner hides behind something, `print3d meet`
finds it where its two edges cross.

The full workflow is in `src/print3d/skill/references/from-photo.md`.

### Benchmark: a LEGO brick from a web photo

![A three-quarter photo of a LEGO 2x4 brick, its top face rectified with the model's outline in blue, and the sliced model](docs/lego-benchmark.jpg)

A three-quarter photo off Wikimedia Commons, no scale reference in it. The top
face is rectified from the brick's 31.8 x 15.8 mm footprint; its back-right
corner is hidden behind a stud and found from its two edges. The studs are then
measured where their bases meet the face, and scored against LEGO's published
dimensions:

| | from the photo | LEGO | error |
| --- | --- | --- | --- |
| stud pitch, along | 8.02 ± 0.22 mm | 8.0 mm | 0.02 mm |
| stud pitch, across | 8.05 ± 0.36 mm | 8.0 mm | 0.05 mm |
| stud to edge | 1.45 ± 0.24 mm | 1.5 mm | 0.05 mm |
| stud diameter (from the three above) | 4.85 mm | 4.8 mm | 0.05 mm |

The brick built from those numbers (`examples/lego_2x4.py`) covers the photo's
top face at 99% and slices clean: 57 layers, 12 minutes, 2.8 g.

What the photo cannot give is recorded as such: the height is given (9.6 mm),
and the stud height is assumed, because a stud stands off the rectified face
and smears with the viewing angle (read straight off the image, a stud looks
7.3 mm wide). One reading went wrong: stud-to-edge measured from the front edge
came out at 1.95 mm, where the base's shadow fades. It is left out of the
table's inputs, which is the call the tolerance cannot make for you.

Replay it with `pytest tests/test_lego_benchmark.py`; the end-to-end Blender and
Studio run is in `tests/test_studio_it.py`. Whether the printed studs grip a
real brick is the next test, and a printer's.

Photo: "Light Green Lego Brick" by Stilfehler,
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Light_Green_Lego_Brick.jpg);
the figure above is shared under the same licence. LEGO is a trademark of the
LEGO Group, which does not sponsor or endorse this project.

## What gets checked

- **The mesh:** overhangs steeper than 45°, bed contact, tall-and-narrow parts,
  parts too thin to print. Supports are off in the pinned preset, so an overhang
  is a real defect.
- **The slice:** print time, filament, and how much material each layer adds.
- **The likeness**, when you worked from a photo: outline overlap and size
  against each photographed view.

Every problem comes with a `fix` telling you what to change in the script.
`jobs/<slug>/history.jsonl` keeps a record of each run.

## Use it from your agent

After `print3d setup`, ask your agent for a part. In Claude Code:

```text
/print3d a 40mm nameplate that says MARCO
/print3d recreate the knob in ~/Desktop/knob.jpg, it sits on a 6 mm D-shaft
```

Codex, Cursor and Gemini get the same steps through MCP: `guide`, `make`,
`grid`, `measure_*`, `likeness` and `check`. Tools that make pictures (the
coordinate grid, the plate preview, the likeness overlays) return them as
images, so the agent sees what it built.

## Develop

```bash
git clone git@github.com:mfranzon/print3d.git && cd print3d
uv venv && uv pip install -e '.[dev]'
.venv/bin/print3d setup                             # point your agents at this checkout
.venv/bin/python -m pytest -q                       # unit tests
PRINT3D_STUDIO_IT=1 .venv/bin/python -m pytest -q   # also runs Blender and Studio
```

In a checkout, jobs go to `jobs/` in the repo.
