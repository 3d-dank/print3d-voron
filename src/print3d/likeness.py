"""Does the model look like the photo?

Printability checks pass on parts that print well and are still the wrong
object. For every view in the spec that has an outline, this projects the
finished STL along the view's camera axis, draws it at the photo's mm-per-pixel,
centres it on the photographed outline, and compares the two:

  - `iou`        overlap at true scale: shape and size together
  - `shape_iou`  overlap with the model stretched onto the photo's box: shape alone
  - size         the two boxes in mm, against what the photo can resolve

The photo is levelled first: up to six degrees of tilt are tried and the best
kept, as `tilt_deg`. It also tries the other seven ways the same silhouette
could be turned or mirrored. A much better match there means the view axes, or the part's
orientation, are wrong rather than the geometry.

The projection is orthographic. A photo taken close up has perspective, which
shrinks what is further away; shoot from a distance and zoom in.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from print3d.dfm import read_stl
from print3d.photo import open_upright, view_mask
from print3d.printability import Advice
from print3d.spec import PICK_ERROR_PX, load_spec, spec_path

IOU_WARN = 0.90
IOU_ERROR = 0.80
# An alternative pose has to beat the declared one clearly, or symmetric parts flip-flop.
ALTERNATIVE_MARGIN = 0.05
MIN_SIZE_TOL_MM = 0.5
WORK_PX = 600
MARGIN = 1.15
# How far off level a photo may be. Zero first, so a level photo stays as it is.
TILTS_DEG = [0.0] + [sign * step / 2 for step in range(1, 13) for sign in (1, -1)]

Vec = tuple[int, int, int]


def _axis(name: str) -> Vec:
    sign = -1 if name[0] == "-" else 1
    return tuple(sign * int(name[1] == axis) for axis in "xyz")  # type: ignore[return-value]


def _name(vec: Vec) -> str:
    index = next(i for i, v in enumerate(vec) if v)
    return ("+" if vec[index] > 0 else "-") + "xyz"[index]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _neg(a: Vec) -> Vec:
    return (-a[0], -a[1], -a[2])


def project(triangles, right: Vec, up: Vec) -> list[list[tuple[float, float]]]:
    """Triangles flattened onto the image plane, in mm, v pointing up."""
    return [
        [(sum(p * r for p, r in zip(v, right)), sum(p * u for p, u in zip(v, up))) for v in tri]
        for tri in triangles
    ]


def extent(flat) -> tuple[float, float]:
    us = [u for tri in flat for u, _ in tri]
    vs = [v for tri in flat for _, v in tri]
    return max(us) - min(us), max(vs) - min(vs)


def silhouette(flat, cell_mm: float) -> Image.Image:
    """The projected mesh as a 1-bit image, one pixel per `cell_mm`."""
    umin = min(u for tri in flat for u, _ in tri)
    vmax = max(v for tri in flat for _, v in tri)
    width_mm, height_mm = extent(flat)
    image = Image.new("1", (max(1, math.ceil(width_mm / cell_mm)), max(1, math.ceil(height_mm / cell_mm))), 0)
    draw = ImageDraw.Draw(image)
    for tri in flat:
        draw.polygon([((u - umin) / cell_mm, (vmax - v) / cell_mm) for u, v in tri], fill=1)
    return image


def fill_holes(image: Image.Image) -> Image.Image:
    """Close through-holes, for comparing against an outline traced as one polygon."""
    padded = Image.new("L", (image.width + 2, image.height + 2), 0)
    padded.paste(image.convert("L"), (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    return padded.point(lambda v: 0 if v == 128 else 255).crop((1, 1, image.width + 1, image.height + 1)).convert("1")


def _poses(image: Image.Image, right: Vec, up: Vec):
    """The eight turns and mirrors of a silhouette, with the camera axes that produce each."""
    for flip in (False, True):
        img, r, u = image, right, up
        if flip:
            img, r = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT), _neg(r)
        for _ in range(4):
            yield img, r, u
            # Turning the picture a quarter counter-clockwise puts what was on the right at the top.
            img, r, u = img.transpose(Image.Transpose.ROTATE_90), _neg(u), r


def _centred(image: Image.Image, side: int) -> Image.Image:
    canvas = Image.new("1", (side, side), 0)
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def _count(image: Image.Image) -> int:
    return image.histogram()[-1]


def _iou(a: Image.Image, b: Image.Image) -> float:
    union = _count(ImageChops.logical_or(a, b))
    return _count(ImageChops.logical_and(a, b)) / union if union else 0.0


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.convert("L").resize(size, Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0).convert("1")


def compare_view(triangles, name: str, view: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    mask = view_mask(view)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError(f"The {name} outline is empty.")
    scale = view["scale"]
    mm_per_px = scale["mm_per_px"]
    look, up = _axis(view["look"]), _axis(view["up"])
    right = _cross(look, up)

    photo_px = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    flat = project(triangles, right, up)
    model_mm = extent(flat)

    # Work on a square canvas big enough for either outline in any of the eight poses.
    span_px = max(*photo_px, *(d / mm_per_px for d in model_mm)) * MARGIN
    shrink = min(1.0, WORK_PX / span_px)
    side = math.ceil(span_px * shrink)
    cell_mm = mm_per_px / shrink
    model = silhouette(flat, cell_mm)
    if "outline" in view:
        model = fill_holes(model)

    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    half = side / shrink / 2
    region = (round(cx - half), round(cy - half), round(cx + half), round(cy + half))
    photo_canvas = mask.crop(region).resize((side, side), Image.NEAREST)

    # Photos are rarely level, and a degree of tilt costs a slender part much of its
    # overlap. Level the photo against the model before comparing anything.
    model_centred = _centred(model, side)
    tilt = max(TILTS_DEG, key=lambda a: _iou(_level(photo_canvas, a, side)[0], model_centred))
    photo_mask, level_box = _level(photo_canvas, tilt, side)
    photo_mm = ((level_box[2] - level_box[0]) * cell_mm, (level_box[3] - level_box[1]) * cell_mm)

    poses = [(_iou(photo_mask, _centred(img, side)), r, u, img) for img, r, u in _poses(model, right, up)]
    iou, _, _, posed = poses[0]
    best_iou, best_right, best_up, _ = max(poses, key=lambda pose: pose[0])

    photo_box = (level_box[2] - level_box[0], level_box[3] - level_box[1])
    shape_iou = _iou(photo_mask, _centred(_fit(model, photo_box), side))

    overlay = out_dir / f"{name}.png"
    base = Image.new("RGB", (region[2] - region[0], region[3] - region[1]), "white")
    # The region can run past the photo's edges; past them is background, not black.
    base.paste(open_upright(Path(view["photo"])), (-region[0], -region[1]))
    base = base.resize((side, side), Image.LANCZOS).rotate(tilt, Image.BICUBIC, fillcolor="white")
    # Shift the levelled photo exactly as its outline was centred.
    level_base = Image.new("RGB", (side, side), "white")
    level_base.paste(base, ((side - photo_box[0]) // 2 - level_box[0], (side - photo_box[1]) // 2 - level_box[1]))
    _draw_overlay(level_base, photo_mask, _centred(posed, side), overlay)

    pick = math.sqrt(2) * PICK_ERROR_PX
    tolerance = [
        max(MIN_SIZE_TOL_MM, 2 * pick * mm_per_px + d * pick / scale["ref_px"]) for d in photo_mm
    ]
    result: dict[str, Any] = {
        "view": name,
        "look": view["look"],
        "up": view["up"],
        "iou": round(iou, 3),
        "shape_iou": round(shape_iou, 3),
        "photo_mm": [round(d, 2) for d in photo_mm],
        "model_mm": [round(d, 2) for d in model_mm],
        "tolerance_mm": [round(t, 2) for t in tolerance],
        "tilt_deg": tilt,
        "overlay": str(overlay),
    }
    if best_iou > iou + ALTERNATIVE_MARGIN:
        result["better_pose"] = {
            "look": _name(_cross(best_up, best_right)),
            "up": _name(best_up),
            "iou": round(best_iou, 3),
        }
    return result


def _level(mask: Image.Image, angle: float, side: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Turn a photo mask by `angle` degrees and centre what is on it; also return its box before centring."""
    turned = mask.rotate(angle, Image.NEAREST, fillcolor=0) if angle else mask
    box = turned.getbbox() or (0, 0, 1, 1)
    return _centred(turned.crop(box), side), box


def _draw_overlay(base: Image.Image, photo_mask, model_mask, out: Path) -> None:
    """Red: in the photo, missing from the model. Blue: in the model, not in the photo.

    The model's outline is drawn in blue as well, so a good match still shows where it sits.
    """
    side = base.width
    only_photo = ImageChops.logical_and(photo_mask, ImageChops.logical_xor(photo_mask, model_mask))
    only_model = ImageChops.logical_and(model_mask, ImageChops.logical_xor(photo_mask, model_mask))
    for mask, colour in ((only_photo, (230, 40, 40)), (only_model, (40, 90, 230))):
        tinted = Image.blend(base, Image.new("RGB", base.size, colour), 0.55)
        base = Image.composite(tinted, base, mask)
    if side < WORK_PX:
        base = base.resize((WORK_PX, WORK_PX), Image.LANCZOS)
        model_mask = model_mask.resize((WORK_PX, WORK_PX), Image.NEAREST)
    filled = model_mask.convert("L")
    edge = ImageChops.subtract(filled, filled.filter(ImageFilter.MinFilter(5)))
    base.paste((40, 90, 230), mask=edge)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out)


def check_likeness(mesh: Path, spec: dict[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    """Compare the mesh with every photographed view that has an outline."""
    views = {name: v for name, v in spec.get("views", {}).items() if "outline" in v or "mask" in v}
    if not views:
        return []
    triangles = read_stl(mesh.expanduser().resolve())
    return [compare_view(triangles, name, view, out_dir) for name, view in views.items()]


def check_job(job_dir: Path, mesh: Path | None = None) -> tuple[list[dict[str, Any]], list[Advice]]:
    """The likeness check on a job's last mesh, outside a full run."""
    mesh = mesh or job_dir / "mesh" / f"{job_dir.name}.stl"
    results = check_likeness(mesh, load_spec(job_dir), job_dir / "likeness")
    if not results:
        raise ValueError(f"No view in {spec_path(job_dir)} has an outline yet.")
    return results, likeness_advice(results)


def likeness_advice(results: list[dict[str, Any]]) -> list[Advice]:
    notes: list[Advice] = []
    for r in results:
        pw, ph = r["photo_mm"]
        mw, mh = r["model_mm"]
        tw, th = r["tolerance_mm"]
        off = [
            f"{axis} {model:.1f} mm vs {photo:.1f} ± {tol:.1f} mm"
            for axis, model, photo, tol in (("width", mw, pw, tw), ("height", mh, ph, th))
            if abs(model - photo) > tol
        ]
        message = (
            f"{r['view']} view: the model covers the photo's outline {r['iou']:.0%} "
            f"({r['shape_iou']:.0%} on shape alone). Photo {pw:.1f} x {ph:.1f} mm, "
            f"model {mw:.1f} x {mh:.1f} mm."
            + (f" The photo was levelled by {r['tilt_deg']:+.1f} deg." if r.get("tilt_deg") else "")
        )
        if "better_pose" in r:
            pose = r["better_pose"]
            severity = "error"
            fix = (
                f"Seen with look={pose['look']} up={pose['up']} the model matches {pose['iou']:.0%}. "
                "Rotate the part to match, or correct the view's --look/--up if the photo was taken from there."
            )
        elif off and r["shape_iou"] >= IOU_WARN:
            severity = "error"
            fix = f"The shape is right, the size is not: {'; '.join(off)}. Change the driving dimension."
        elif r["iou"] < IOU_ERROR or off:
            severity = "error"
            fix = (
                f"Look at {r['overlay']}: red is in the photo but missing from the model, blue is model "
                "the photo does not show. Change the geometry there."
                + (f" Size: {'; '.join(off)}." if off else "")
            )
        elif r["iou"] < IOU_WARN:
            severity = "warn"
            fix = f"Close. Look at {r['overlay']} for where the outlines part."
        else:
            severity = "note"
            fix = "Matches the photo."
        notes.append(Advice("likeness", severity, message, fix))
    return notes
