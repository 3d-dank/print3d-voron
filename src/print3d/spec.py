"""What we know about the object, and how we know it.

`jobs/<slug>/spec.json` is the evidence behind a model built from photos. Every
dimension carries its source - measured off a photo, given by the user, quoted
from a shop listing, or assumed - and a measured one keeps the pixels and the
scale reference it came from, so a wrong number can be traced back and
re-measured instead of argued.

    listing:   the product being replaced, when there is one: where it is sold
               and what it costs
    views:     per photo: the file, its scale reference, the camera axes, and
               optionally the object's outline for the likeness check
    dims:      name -> mm, source, tolerance, evidence
    unknowns:  what no photo shows
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from print3d.photo import rectify

SPEC = "spec.json"

# Objects people photograph next to a part, by the length the points span.
REFERENCES_MM = {
    "card": 85.6,  # ISO/IEC 7810 ID-1: bank card, ID card, long edge
    "card-short": 53.98,
    "a4": 297.0,
    "a4-short": 210.0,
    "letter": 279.4,
    "letter-short": 215.9,
    "euro-1": 23.25,
    "euro-2": 25.75,
    "euro-0.50": 24.25,
    "us-quarter": 24.26,
    "us-penny": 19.05,
    "uk-pound": 23.43,
}

# How far off a picked point can be, in photo pixels, when read off a grid crop.
PICK_ERROR_PX = 3.0

# Default camera axes per view name, in the printed part's frame (z up off the bed).
# `look` is the direction the camera looks along; `up` is up in the photo.
VIEW_AXES = {
    "front": ("+y", "+z"),
    "back": ("-y", "+z"),
    "left": ("+x", "+z"),
    "right": ("-x", "+z"),
    "top": ("-z", "+y"),
    "bottom": ("+z", "-y"),
}
AXES = ("+x", "-x", "+y", "-y", "+z", "-z")


class SpecError(ValueError):
    """Raised for a spec edit that cannot be honoured."""


def spec_path(job_dir: Path) -> Path:
    return job_dir / SPEC


def load_spec(job_dir: Path) -> dict[str, Any]:
    path = spec_path(job_dir)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"views": {}, "dims": {}, "unknowns": []}


def save_spec(job_dir: Path, spec: dict[str, Any]) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = spec_path(job_dir)
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return path


def parse_points(text: str, *, count: int | None = None) -> list[list[float]]:
    """`"x1,y1,x2,y2,..."` -> `[[x1, y1], [x2, y2], ...]`."""
    try:
        values = [float(v) for v in text.replace(" ", "").split(",") if v]
    except ValueError as exc:
        raise SpecError(f"Points must be numbers: {text!r}") from exc
    if len(values) % 2:
        raise SpecError(f"Points come in x,y pairs; got {len(values)} numbers.")
    points = [values[i : i + 2] for i in range(0, len(values), 2)]
    if count is not None and len(points) != count:
        raise SpecError(f"Expected {count} points, got {len(points)}.")
    return points


def _span(points: list[list[float]]) -> float:
    (x1, y1), (x2, y2) = points
    return math.hypot(x2 - x1, y2 - y1)


# A listed size is rounded: whole millimetres unless the listing says otherwise.
LISTING_TOLERANCE_MM = 0.5


def reference_mm(spec: dict[str, Any], ref: str) -> tuple[float, float]:
    """The reference's length and how far off that length can be, both in mm."""
    if ref.startswith("dim:"):
        dim = spec["dims"].get(ref[4:])
        if dim is None or dim["source"] not in ("user", "listing"):
            raise SpecError(f"{ref!r} must name a dimension given by the user or quoted from the listing.")
        return dim["mm"], dim.get("tolerance_mm", 0.0)
    if ref in REFERENCES_MM:
        return REFERENCES_MM[ref], 0.0
    try:
        return float(ref), 0.0
    except ValueError:
        known = ", ".join(sorted(REFERENCES_MM))
        raise SpecError(
            f"Unknown reference {ref!r}. Use a length in mm, dim:<name> for a listed dimension, or one of: {known}."
        ) from None


def set_scale(
    spec: dict[str, Any],
    view: str,
    photo: Path,
    ref: str,
    points: list[list[float]],
    *,
    look: str | None = None,
    up: str | None = None,
) -> dict[str, Any]:
    ref_px = _span(points)
    if ref_px < 1.0:
        raise SpecError("The reference points coincide.")
    default_look, default_up = VIEW_AXES.get(view, (None, None))
    look, up = look or default_look, up or default_up
    if look is None or up is None:
        raise SpecError(f"View {view!r} is not one of {', '.join(VIEW_AXES)}; pass --look and --up.")
    if look not in AXES or up not in AXES or look[1] == up[1]:
        raise SpecError(f"--look and --up must be two different axes from {', '.join(AXES)}.")
    ref_len, ref_tol = reference_mm(spec, ref)
    entry = spec["views"].setdefault(view, {})
    entry.update(
        {
            "photo": str(photo.expanduser().resolve()),
            "look": look,
            "up": up,
            "scale": {
                "ref": ref,
                "ref_mm": ref_len,
                "ref_tolerance_mm": ref_tol,
                "points": points,
                "ref_px": round(ref_px, 2),
                "mm_per_px": ref_len / ref_px,
            },
            "assumes": "The reference lies in the same plane as what is measured, "
            "and the photo is taken square-on from a distance.",
        }
    )
    return entry


def rectify_view(
    spec: dict[str, Any],
    view: str,
    photo: Path,
    corners: list[list[float]],
    size_mm: tuple[float, float],
    out: Path,
    *,
    look: str | None = None,
    up: str | None = None,
) -> dict[str, Any]:
    """Scale a view from a flat face of known size, seen at an angle.

    The view's photo becomes the rectified image: every later point for this view
    is read off that image, where the face is square-on.
    """
    warped = rectify(photo, [tuple(c) for c in corners], size_mm, out)
    (x0, y0), (x1, _), *_ = warped["face_px"]
    entry = set_scale(spec, view, out, str(size_mm[0]), [[x0, y0], [x1, y0]], look=look, up=up)
    # Picking error lives in the original photo, where the face was smaller.
    entry["scale"]["ref_px"] = round(warped["shortest_edge_photo_px"], 2)
    entry["rectified"] = {
        "from_photo": str(photo.expanduser().resolve()),
        "corners": corners,
        "size_mm": list(size_mm),
    }
    entry["assumes"] = (
        "What is measured lies in the rectified face. Anything standing off it, "
        "like a boss or a stud, shifts with the viewing angle."
    )
    return entry


def _view(spec: dict[str, Any], view: str) -> dict[str, Any]:
    entry = spec["views"].get(view)
    if not entry or "scale" not in entry:
        raise SpecError(f"View {view!r} has no scale yet. Run: print3d measure <slug> scale {view} ...")
    return entry


def mm_tolerance(scale: dict[str, Any], mm: float, pick_px: float) -> float:
    """How far off a length read off a scaled view can be.

    The feature's own picking error, plus the reference's picking error and its
    stated rounding, both carried as a ratio of the length.
    """
    ref_ratio = pick_px / scale["ref_px"] + scale.get("ref_tolerance_mm", 0.0) / scale["ref_mm"]
    return pick_px * scale["mm_per_px"] + mm * ref_ratio


def measure_dim(spec: dict[str, Any], name: str, view: str, points: list[list[float]]) -> dict[str, Any]:
    scale = _view(spec, view)["scale"]
    px = _span(points)
    mm = px * scale["mm_per_px"]
    tolerance = mm_tolerance(scale, mm, math.sqrt(2) * PICK_ERROR_PX)
    entry = {
        "mm": round(mm, 2),
        "source": "measured",
        "tolerance_mm": round(tolerance, 2),
        "view": view,
        "points": points,
        "px": round(px, 2),
    }
    spec["dims"][name] = entry
    return entry


def given_dim(spec: dict[str, Any], name: str, mm: float, source: str, why: str | None) -> dict[str, Any]:
    if source not in ("user", "assumed"):
        raise SpecError("A dimension typed in is either `user` (they said so) or `assumed` (you chose it).")
    if source == "assumed" and not why:
        raise SpecError("Say why: an assumed dimension needs --why.")
    entry: dict[str, Any] = {"mm": mm, "source": source}
    if why:
        entry["why"] = why
    spec["dims"][name] = entry
    return entry


def listing_dim(
    spec: dict[str, Any], name: str, mm: float, quote: str | None, tolerance_mm: float | None = None
) -> dict[str, Any]:
    """A dimension the shop states. The quote is the evidence: the listing's own words."""
    if not quote:
        raise SpecError("Quote the listing: a listed dimension needs the text it was read from (--quote).")
    entry = {
        "mm": mm,
        "source": "listing",
        "tolerance_mm": LISTING_TOLERANCE_MM if tolerance_mm is None else tolerance_mm,
        "quote": quote,
    }
    spec["dims"][name] = entry
    return entry


def set_listing(
    spec: dict[str, Any],
    url: str,
    name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """The product the part replaces: where its listed dimensions and photos come from."""
    listing = {"url": url, "name": name, "price": price, "currency": currency}
    spec["listing"] = {k: v for k, v in listing.items() if v is not None}
    return spec["listing"]


def set_outline(
    spec: dict[str, Any], view: str, *, points: list[list[float]] | None = None, mask: Path | None = None
) -> dict[str, Any]:
    entry = _view(spec, view)
    if points is not None:
        if len(points) < 3:
            raise SpecError("An outline needs at least 3 points.")
        entry["outline"] = points
        entry.pop("mask", None)
    elif mask is not None:
        entry["mask"] = str(mask.expanduser().resolve())
        entry.pop("outline", None)
    else:
        raise SpecError("Give the outline as --points or --mask.")
    return entry


def add_unknown(spec: dict[str, Any], text: str) -> list[str]:
    if text not in spec["unknowns"]:
        spec["unknowns"].append(text)
    return spec["unknowns"]


def model_dims(spec: dict[str, Any]) -> dict[str, float]:
    """What a model script sees as `params["dims"]`."""
    return {name: entry["mm"] for name, entry in spec.get("dims", {}).items()}
