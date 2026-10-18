"""print3d as an MCP server, for any agent that speaks MCP.

The same operations as the CLI. Tools that produce pictures (the coordinate
grid, the plate preview, the likeness overlays) return them as images, so the
agent sees them without a separate file read.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from print3d import spec as specs
from print3d.likeness import check_job
from print3d.paths import default_jobs_dir, skill_dir
from print3d.photo import grid as draw_grid
from print3d.pipeline import run_job
from print3d.printability import advise, analyze_mesh, analyze_slice

INSTRUCTIONS = """\
print3d turns an idea, or a photo of an object, into a Bambu Studio project for a
Bambu Lab X2D. You write a Blender (bpy) model script; `make` runs it, checks the
mesh, slices it and returns advice, each note with the fix to apply to the script.
Iterate until no note is at `error`, then hand the user the .3mf path.

Read guide("workflow") before the first run. From a photo of an object, also read
guide("from-photo"): it records every dimension with its evidence and adds a
likeness check against the photo. Nothing here sends anything to the printer.
"""

GUIDES = {
    "workflow": "SKILL.md",
    "modelling": "references/modelling.md",
    "from-photo": "references/from-photo.md",
}

server = MCPServer("print3d", instructions=INSTRUCTIONS)


def tool(*, images: bool = False):
    """Register a tool. print3d errors already say what to change, so the agent gets their text."""

    def register(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                raise ToolError(str(exc)) from exc

        return server.tool(structured_output=False if images else None)(wrapper)

    return register


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2)


def _job(slug: str) -> Path:
    return default_jobs_dir() / slug


def _saved(slug: str, spec: dict[str, Any], entry: Any) -> str:
    return _json({"saved": str(specs.save_spec(_job(slug), spec)), "entry": entry})


def _with_images(payload: dict[str, Any], paths: list[str | None]) -> list[Any]:
    return [_json(payload), *(Image(path=p) for p in paths if p and Path(p).is_file())]


@tool()
def guide(topic: Literal["workflow", "modelling", "from-photo"]) -> str:
    """How to use print3d: the loop, bpy recipes and gotchas, or reverse-engineering from a photo."""
    return (skill_dir() / GUIDES[topic]).read_text(encoding="utf-8")


@tool(images=True)
def make(
    prompt: str,
    script: str | None = None,
    mesh: str | None = None,
    color: str | None = None,
    dry_run: bool = False,
) -> list[Any]:
    """Model, check and slice. With no model yet, writes a starter model.py and names its path.

    Returns the report, then the plate preview and any likeness overlays.
    """
    report = run_job(
        prompt,
        script=Path(script) if script else None,
        mesh=Path(mesh) if mesh else None,
        color=color,
        execute=not dry_run,
    )
    overlays = [r["overlay"] for r in report.get("likeness", [])]
    return _with_images(report, [report.get("plate_png"), *overlays])


@tool(images=True)
def grid(photo: str, crop: list[float] | None = None, step: int | None = None) -> list[Any]:
    """A photo, or a zoomed crop [x0, y0, x1, y1] of it, with photo-pixel coordinates drawn on.

    Read every point you measure off a crop: labels are photo pixels.
    """
    if crop is not None and len(crop) != 4:
        raise ValueError("crop is [x0, y0, x1, y1]")
    result = draw_grid(Path(photo), crop=tuple(crop) if crop else None, step=step)
    return _with_images(result, [str(result["grid"])])


@tool()
def measure_scale(
    slug: str,
    view: str,
    photo: str,
    ref: str,
    points: list[list[float]],
    look: str | None = None,
    up: str | None = None,
) -> str:
    """Scale a photo from a reference of known length in it.

    `ref` is a length in mm or one of: card, card-short, a4, a4-short, letter,
    letter-short, euro-1, euro-2, euro-0.50, us-quarter, us-penny, uk-pound.
    `points` are the reference's two ends. Views front/back/left/right/top/bottom
    set the camera axes; for another pose pass look/up (+x, -y, ...) in the printed part.
    """
    spec = specs.load_spec(_job(slug))
    entry = specs.set_scale(spec, view, Path(photo), ref, points, look=look, up=up)
    return _saved(slug, spec, entry)


@tool()
def measure_dim(
    slug: str,
    name: str,
    view: str | None = None,
    points: list[list[float]] | None = None,
    mm: float | None = None,
    source: Literal["user", "assumed"] | None = None,
    why: str | None = None,
) -> str:
    """Record a dimension: measured from two points in a scaled view, or typed in as given or assumed.

    The model script reads it as params["dims"][name].
    """
    spec = specs.load_spec(_job(slug))
    if mm is not None:
        entry = specs.given_dim(spec, name, mm, source or "", why)
    elif view and points:
        entry = specs.measure_dim(spec, name, view, points)
    else:
        raise ValueError("Give view and points to measure, or mm and source to type it in.")
    return _saved(slug, spec, entry)


@tool()
def measure_outline(
    slug: str, view: str, points: list[list[float]] | None = None, mask: str | None = None
) -> str:
    """The object's outline in a view, as a polygon in photo pixels or a photo-sized mask PNG.

    Every outlined view adds a likeness check to `make`.
    """
    spec = specs.load_spec(_job(slug))
    entry = specs.set_outline(spec, view, points=points, mask=Path(mask) if mask else None)
    return _saved(slug, spec, entry)


@tool()
def add_unknown(slug: str, text: str) -> str:
    """Record something no photo shows, for the user to check on the printed part."""
    spec = specs.load_spec(_job(slug))
    return _saved(slug, spec, specs.add_unknown(spec, text))


@tool()
def show_spec(slug: str) -> str:
    """Everything recorded about the object: views, dimensions with their evidence, unknowns."""
    return _json(specs.load_spec(_job(slug)))


@tool(images=True)
def likeness(slug: str, mesh: str | None = None) -> list[Any]:
    """Compare the job's mesh with every outlined photo view. Returns results, advice and overlays."""
    results, notes = check_job(_job(slug), Path(mesh) if mesh else None)
    payload = {"likeness": results, "advice": [note.as_dict() for note in notes]}
    return _with_images(payload, [r["overlay"] for r in results])


@tool()
def check(mesh: str, project: str | None = None) -> str:
    """Printability of an existing STL, and of its sliced .gcode.3mf when given."""
    mesh_metrics = analyze_mesh(Path(mesh))
    slice_metrics = analyze_slice(Path(project)) if project else None
    notes = advise(mesh_metrics, slice_metrics)
    return _json({"mesh_metrics": mesh_metrics, "advice": [note.as_dict() for note in notes]})


def main() -> None:
    server.run("stdio")
