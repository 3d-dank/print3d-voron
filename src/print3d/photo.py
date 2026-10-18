"""Reading pixel positions off a photo.

A vision model guesses coordinates to within a few percent of the image. That is
centimetres on a desk photo. `grid` draws labelled pixel coordinates over the
photo, or over a zoomed crop of it, so points are read off a ruler instead.

Every coordinate here is in the *upright* photo: EXIF rotation applied, which is
also how an image viewer shows it.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from print3d.paths import default_jobs_dir

GRID_LONG_SIDE_PX = 1600
MAX_ZOOM = 8.0
NICE_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)


def open_upright(photo: Path) -> Image.Image:
    with Image.open(photo.expanduser()) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _nice_step(span: float, lines: int = 16) -> int:
    target = span / lines
    return next((s for s in NICE_STEPS if s >= target), NICE_STEPS[-1])


def grid(
    photo: Path,
    out: Path | None = None,
    *,
    crop: tuple[float, float, float, float] | None = None,
    step: int | None = None,
) -> dict[str, object]:
    """Draw labelled photo-pixel coordinates over the photo or a crop of it."""
    if out is None:
        suffix = "_" + "_".join(str(int(v)) for v in crop) if crop else ""
        out = default_jobs_dir() / "grid" / f"{photo.stem}{suffix}.png"
    image = open_upright(photo)
    width, height = image.size
    x0, y0, x1, y1 = crop or (0, 0, width, height)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(width, int(x1)), min(height, int(y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise ValueError(f"Crop {crop} is empty inside a {width}x{height} photo.")
    region = image.crop((x0, y0, x1, y1))
    zoom = min(MAX_ZOOM, GRID_LONG_SIDE_PX / max(region.size))
    view = region.resize((round(region.width * zoom), round(region.height * zoom)), Image.LANCZOS)
    step = step or _nice_step(max(x1 - x0, y1 - y0))

    draw = ImageDraw.Draw(view, "RGBA")
    font = ImageFont.load_default(size=max(12, GRID_LONG_SIDE_PX // 90))
    line, label = (255, 0, 255, 150), (255, 255, 255, 255)
    for x in range(-(-x0 // step) * step, x1 + 1, step):
        px = (x - x0) * zoom
        draw.line([(px, 0), (px, view.height)], fill=line, width=1)
        draw.text((px + 2, 2), str(x), fill=label, font=font, stroke_width=2, stroke_fill="black")
    for y in range(-(-y0 // step) * step, y1 + 1, step):
        py = (y - y0) * zoom
        draw.line([(0, py), (view.width, py)], fill=line, width=1)
        draw.text((2, py + 2), str(y), fill=label, font=font, stroke_width=2, stroke_fill="black")

    out.parent.mkdir(parents=True, exist_ok=True)
    view.save(out)
    return {
        "grid": str(out),
        "photo_size_px": [width, height],
        "crop": [x0, y0, x1, y1],
        "step_px": step,
        "zoom": round(zoom, 3),
        "next_step": "Labels are photo pixels. Crop tighter around a feature to read its ends more precisely.",
    }


def view_mask(view: dict) -> Image.Image:
    """The object's silhouette in a photo, as a 1-bit image in photo pixels."""
    size = open_upright(Path(view["photo"])).size
    if "outline" in view:
        mask = Image.new("1", size, 0)
        ImageDraw.Draw(mask).polygon([tuple(p) for p in view["outline"]], fill=1)
        return mask
    with Image.open(view["mask"]) as raw:
        upright = ImageOps.exif_transpose(raw)
        # A background remover leaves the object opaque; a hand-made mask paints it white.
        grey = upright.getchannel("A") if "A" in upright.getbands() else upright.convert("L")
        mask = grey.point(lambda v: 255 if v > 127 else 0).convert("1")
    if mask.size != size:
        raise ValueError(f"Mask is {mask.size[0]}x{mask.size[1]} but the photo is {size[0]}x{size[1]}.")
    return mask
