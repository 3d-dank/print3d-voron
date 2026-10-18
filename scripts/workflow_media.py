"""Render the photo-to-print workflow as stills, an MP4 and a GIF, from real runs.

Replays the LEGO benchmark (tests/fixtures/lego_2x4.*) through the actual
pipeline, renders a turntable of the resulting mesh in Blender, and lays each
step out as a 1280x720 frame. Needs Blender, Bambu Studio and ffmpeg.

    .venv/bin/python scripts/workflow_media.py        # writes docs/workflow*
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from print3d.blender import find_blender  # noqa: E402
from print3d.photo import grid, meet, open_upright  # noqa: E402
from print3d.pipeline import run_job  # noqa: E402
from test_lego_benchmark import BENCH, TRUTH, build_spec  # noqa: E402

W, H = 1280, 720
HEAD = 132
GREEN = (0, 174, 66)
INK = (26, 26, 26)
GREY = (110, 110, 110)
RED = (220, 50, 50)
BLUE = (40, 90, 230)
FPS = 24
HOLD_S = 3.2
FADE_S = 0.4
PROMPT = "a lego 2x4 brick"
SLUG = "a_lego_2x4_brick"
OUT = ROOT / "docs"

TURNTABLE = r'''
import bpy, math, sys
argv = sys.argv[sys.argv.index("--") + 1:]
stl, out_dir, frames = argv[0], argv[1], int(argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=stl)
part = bpy.context.selected_objects[0]
part.data.materials.append(bpy.data.materials.new("pla"))
part.active_material.diffuse_color = (0.0, 0.68, 0.26, 1.0)
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_cavity = True
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = 720, 540
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 70
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
target = bpy.data.objects.new("target", None)
scene.collection.objects.link(target)
target.location = (0, 0, 5)
track = cam.constraints.new("TRACK_TO")
track.target = target
for i in range(frames):
    a = 2 * math.pi * i / frames + math.radians(-35)
    cam.location = (95 * math.cos(a), 95 * math.sin(a), 62)
    scene.render.filepath = f"{out_dir}/turn_{i:03d}.png"
    bpy.ops.render.render(write_still=True)
'''


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = "/System/Library/Fonts/Menlo.ttc" if mono else "/System/Library/Fonts/Helvetica.ttc"
    try:
        return ImageFont.truetype(path, size, index=1 if bold and not mono else 0)
    except OSError:
        return ImageFont.load_default(size=size)


def fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    scale = min(box[0] / image.width, box[1] / image.height)
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)


def frame(step: int, total: int, title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([48, 40, 128, 80], radius=20, fill=GREEN)
    draw.text((88, 60), f"{step}/{total}", font=font(22, bold=True), fill="white", anchor="mm")
    draw.text((148, 60), title, font=font(38, bold=True), fill=INK, anchor="lm")
    draw.text((148, 100), subtitle, font=font(22), fill=GREY, anchor="lm")
    draw.text((W - 40, H - 24), "print3d", font=font(18, bold=True), fill=GREEN, anchor="rm")
    return canvas, draw


def paste(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, float]:
    """Fit `image` centred in box (x0, y0, x1, y1); return its offset and scale."""
    x0, y0, x1, y1 = box
    fitted = fit(image, (x1 - x0, y1 - y0))
    ox, oy = x0 + (x1 - x0 - fitted.width) // 2, y0 + (y1 - y0 - fitted.height) // 2
    canvas.paste(fitted, (ox, oy), fitted if fitted.mode == "RGBA" else None)
    return ox, oy, fitted.width / image.width


def arrow(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.line([(x - 22, y), (x + 18, y)], fill=GREEN, width=6)
    draw.polygon([(x + 28, y), (x + 12, y - 12), (x + 12, y + 12)], fill=GREEN)


def dimension(draw, a, b, label, colour, fnt, offset=(0, -14)):
    draw.line([a, b], fill=colour, width=4)
    for p in (a, b):
        draw.ellipse([p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6], fill=colour)
    mid = ((a[0] + b[0]) / 2 + offset[0], (a[1] + b[1]) / 2 + offset[1])
    draw.text(mid, label, font=fnt, fill=colour, anchor="mb", stroke_width=4, stroke_fill="white")


def run(work: Path) -> tuple[dict, Path]:
    job = work / "jobs" / SLUG
    build_spec(job)
    report = run_job(PROMPT, script=ROOT / "examples" / "lego_2x4.py", jobs_dir=work / "jobs", execute=True)
    if report["severity"] == "error":
        raise SystemExit(f"The benchmark run is red: {report['advice']}")
    return report, job


def turntable(mesh: Path, out: Path, frames: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    script = out / "turntable.py"
    script.write_text(TURNTABLE, encoding="utf-8")
    subprocess.run(
        [str(find_blender()), "--background", "--factory-startup", "--python", str(script),
         "--", str(mesh), str(out), str(frames)],
        check=True, capture_output=True,
    )
    return sorted(out.glob("turn_*.png"))


def build_frames(report: dict, job: Path, turn: list[Path], work: Path) -> list[list[Image.Image]]:
    """Each step as a list of images: one for a still, many for an animated step."""
    total = 8
    photo = open_upright(ROOT / "tests" / "fixtures" / "lego_2x4.jpg")
    face = BENCH["top_face"]
    hidden = meet(*face["back_edge"], *face["right_edge"])
    quad = [tuple(face["back_left"]), hidden, tuple(face["front_right"]), tuple(face["front_left"])]
    dims = json.loads((job / "spec.json").read_text())["dims"]
    body = (48, HEAD + 16, W - 48, H - 56)
    steps: list[list[Image.Image]] = []

    # 1. The photo.
    canvas, draw = frame(1, total, "A photo from the web", "Three-quarter view, no ruler, no card. Wikimedia Commons, CC BY-SA 3.0.")
    paste(canvas, photo, body)
    steps.append([canvas])

    # 2. Grid.
    crop = (820, 180, 940, 290)
    grid_png = Path(grid(ROOT / "tests" / "fixtures" / "lego_2x4.jpg", work / "grid.png", crop=crop, step=10)["grid"])
    canvas, draw = frame(2, total, "Read pixels off a grid", "print3d grid --crop zooms in; labels are photo pixels, so points are read, not guessed.")
    marked = photo.copy()
    ImageDraw.Draw(marked).rectangle(crop, outline=RED, width=5)
    paste(canvas, marked, (48, HEAD + 40, 600, H - 80))
    arrow(draw, 640, (HEAD + H) // 2)
    paste(canvas, open_upright(grid_png), (690, HEAD + 16, W - 48, H - 56))
    steps.append([canvas])

    # 3. The hidden corner.
    canvas, draw = frame(3, total, "Find the corner a stud hides", "print3d meet crosses the back edge and the right edge.")
    annotated = photo.copy()
    d = ImageDraw.Draw(annotated)
    d.line(quad + [quad[0]], fill=GREEN, width=3)
    for a, b in (face["back_edge"], face["right_edge"]):
        # Run each edge from its first point through the corner and a little past it.
        far = (hidden[0] + (hidden[0] - a[0]) * 0.12, hidden[1] + (hidden[1] - a[1]) * 0.12)
        d.line([tuple(a), far], fill=BLUE, width=5)
        for x, y in (a, b):
            d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=BLUE, outline="white", width=2)
    d.ellipse([hidden[0] - 16, hidden[1] - 16, hidden[0] + 16, hidden[1] + 16], outline=RED, width=6)
    d.text((hidden[0] + 26, hidden[1] - 40), "hidden corner", font=font(30, bold=True), fill=RED,
           stroke_width=4, stroke_fill="white")
    paste(canvas, annotated, body)
    plain = photo.copy()
    ImageDraw.Draw(plain).line(quad + [quad[0]], fill=GREEN, width=5)
    steps.append([canvas])

    # 4. Rectify.
    canvas, draw = frame(4, total, "Straighten the top face", "measure rectify: four corners and the footprint, 31.8 x 15.8 mm. Now it is seen square-on.")
    paste(canvas, plain, (48, HEAD + 40, 600, H - 80))
    arrow(draw, 640, (HEAD + H) // 2)
    rectified = open_upright(job / "views" / "top.png")
    paste(canvas, rectified, (690, HEAD + 16, W - 48, H - 56))
    steps.append([canvas])

    # 5. Measure.
    canvas, draw = frame(5, total, "Measure, with evidence", "Each number keeps its pixels, its reference and a tolerance. What the photo cannot show is labelled.")
    ann = rectified.copy()
    d = ImageDraw.Draw(ann)
    f = font(30, bold=True)
    pts = BENCH["rectified_points"]
    dimension(d, tuple(pts["stud_span"][0]), tuple(pts["stud_span"][1]), f"3 x {dims['stud_span']['mm'] / 3:.2f} mm", RED, f, (0, 60))
    dimension(d, tuple(pts["row_pitch"][0]), tuple(pts["row_pitch"][1]), f"{dims['row_pitch']['mm']:.2f}", BLUE, f, (-58, 18))
    paste(canvas, ann, (48, HEAD + 16, 700, H - 56))
    mono, mono_b = font(19, mono=True), font(19, mono=True)
    rows = [("dimension", "mm", "source")] + [
        (name, f"{v['mm']:.2f}" + (f" ±{v['tolerance_mm']:.2f}" if "tolerance_mm" in v else ""), v["source"])
        for name, v in dims.items()
    ]
    y = HEAD + 60
    for i, (name, mm, source) in enumerate(rows):
        colour = GREY if i == 0 else {"measured": GREEN, "user": INK, "assumed": RED}.get(source, INK)
        draw.text((740, y), name, font=mono_b, fill=INK if i else GREY)
        draw.text((930, y), mm, font=mono, fill=INK if i else GREY)
        draw.text((1100, y), source, font=mono, fill=colour)
        y += 40 if i == 0 else 34
    draw.text((740, y + 20), "spec.json", font=font(20, bold=True), fill=GREY)
    steps.append([canvas])

    # 6. Model (animated).
    code = [
        'd = params["dims"]',
        'pitch = d["stud_span"] / 3',
        "# the studs sit symmetrically:",
        'radius = (length - d["stud_span"]) / 2',
        '         - d["stud_margin"]',
        "# a box and 8 studs, unioned",
    ]
    animated = []
    for path in turn:
        canvas, draw = frame(6, total, "Model it from the spec", "A Blender script reads params[\"dims\"]: no number of its own.")
        y = HEAD + 120
        for line in code:
            draw.text((60, y), line, font=font(19, mono=True), fill=GREY if line.startswith("#") else INK)
            y += 36
        paste(canvas, open_upright(path), (620, HEAD + 16, W - 48, H - 56))
        animated.append(canvas)
    steps.append(animated)

    # 7. Likeness.
    [like] = report["likeness"]
    canvas, draw = frame(7, total, "Check it matches the photo", "The model is projected from above and laid over the rectified photo. A mismatch fails the run.")
    paste(canvas, open_upright(Path(like["overlay"])), (48, HEAD + 16, 720, H - 56))
    draw.text((780, 300), f"{like['iou']:.0%}", font=font(120, bold=True), fill=GREEN, anchor="lm")
    draw.text((784, 390), "overlap with the photo", font=font(26), fill=INK, anchor="lm")
    draw.text((784, 440), f"photo {like['photo_mm'][0]:.1f} x {like['photo_mm'][1]:.1f} mm", font=font(22), fill=GREY, anchor="lm")
    draw.text((784, 474), f"model {like['model_mm'][0]:.1f} x {like['model_mm'][1]:.1f} mm", font=font(22), fill=GREY, anchor="lm")
    steps.append([canvas])

    # 8. Slice.
    m = report["slice_metrics"]
    canvas, draw = frame(8, total, "Sliced for the Bambu X2D", "Overhangs, bed contact and thin walls checked. Open the .3mf in Bambu Studio and print.")
    paste(canvas, open_upright(Path(report["plate_png"])), (48, HEAD + 16, 640, H - 56))
    stats = [(f"{m['layer_count']}", "layers"), (m["estimated_time"], "print time"), (f"{m['filament_g']:.1f} g", "PLA")]
    y = 230
    for value, label in stats:
        draw.text((700, y), value, font=font(64, bold=True), fill=INK, anchor="ls")
        draw.text((704, y + 32), label, font=font(22), fill=GREY, anchor="ls")
        y += 120
    draw.text((700, H - 90), f"jobs/{SLUG}/slice/{SLUG}.3mf", font=font(18, mono=True), fill=GREEN)
    steps.append([canvas])
    return steps


def results_card(dims: dict) -> Image.Image:
    canvas = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((W // 2, 110), "Photo in, printable part out", font=font(54, bold=True), fill=INK, anchor="mm")
    draw.text((W // 2, 170), "Scored against LEGO's published dimensions", font=font(26), fill=GREY, anchor="mm")
    span, row, margin = dims["stud_span"], dims["row_pitch"], dims["stud_margin"]
    rows = [
        ("stud pitch, along", f"{span['mm'] / 3:.2f} ± {span['tolerance_mm'] / 3:.2f}", f"{TRUTH['stud_pitch']} mm"),
        ("stud pitch, across", f"{row['mm']:.2f} ± {row['tolerance_mm']:.2f}", f"{TRUTH['stud_pitch']} mm"),
        ("stud to edge", f"{margin['mm']:.2f} ± {margin['tolerance_mm']:.2f}", f"{TRUTH['stud_margin']} mm"),
        ("stud diameter (derived)", f"{dims['length']['mm'] - span['mm'] - 2 * margin['mm']:.2f}",
         f"{TRUTH['stud_diameter']} mm"),
    ]
    head = font(24, bold=True)
    for x, label in ((260, ""), (660, "from the photo, mm"), (960, "LEGO")):
        draw.text((x, 260), label, font=head, fill=GREY, anchor="lm")
    y = 320
    for name, got, truth in rows:
        draw.line([(240, y - 30), (1060, y - 30)], fill=(230, 230, 230), width=2)
        draw.text((260, y), name, font=font(30), fill=INK, anchor="lm")
        draw.text((660, y), got, font=font(30, bold=True), fill=GREEN, anchor="lm")
        draw.text((960, y), truth, font=font(30), fill=INK, anchor="lm")
        y += 70
    draw.text((W // 2, H - 80), "github.com/mfranzon/print3d", font=font(26, bold=True), fill=GREEN, anchor="mm")
    return canvas


def encode(steps: list[list[Image.Image]], work: Path) -> None:
    seq = work / "seq"
    seq.mkdir()
    hold, fade = round(HOLD_S * FPS), round(FADE_S * FPS)
    images: list[Image.Image] = []
    for i, step in enumerate(steps):
        # An animated step loops its frames for the hold; a still repeats.
        run_ = [step[j % len(step)] for j in range(max(hold, len(step) * 2))] if len(step) > 1 else [step[0]] * hold
        if images:
            prev = images[-1]
            images += [Image.blend(prev, run_[0], (k + 1) / (fade + 1)) for k in range(fade)]
        images += run_
    images += [images[-1]] * FPS
    for n, image in enumerate(images):
        image.save(seq / f"{n:05d}.png")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found; stills are in docs/workflow/")
    pattern = str(seq / "%05d.png")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(OUT / "workflow.mp4")], check=True)
    palette = work / "palette.png"
    scale = "fps=12,scale=800:-1:flags=lanczos"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern,
                    "-vf", f"{scale},palettegen=stats_mode=diff", str(palette)], check=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern, "-i", str(palette),
                    "-lavfi", f"{scale} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    str(OUT / "workflow.gif")], check=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        report, job = run(work)
        turn = turntable(Path(report["model"]["mesh"]), work / "turn", frames=36)
        steps = build_frames(report, job, turn, work)
        dims = json.loads((job / "spec.json").read_text())["dims"]
        steps.append([results_card(dims)])

        stills = OUT / "workflow"
        stills.mkdir(parents=True, exist_ok=True)
        names = ["photo", "grid", "hidden-corner", "rectify", "measure", "model", "likeness", "slice", "results"]
        for n, (name, step) in enumerate(zip(names, steps), start=1):
            step[len(step) // 3].save(stills / f"{n:02d}-{name}.png", optimize=True)
        encode(steps, work)
    for path in sorted(OUT.glob("workflow*")) + sorted((OUT / "workflow").glob("*.png")):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB" if path.is_file() else "")


if __name__ == "__main__":
    main()
