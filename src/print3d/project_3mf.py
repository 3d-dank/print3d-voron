"""Write a PrusaSlicer-format 3MF: one object per printed object, one volume per part."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

from print3d.dfm import read_stl
from print3d.slicer import Part, SlicerError

GAP_MM = 5.0
MARGIN_MM = 5.0
IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
# Bambu / Orca setting names the model scripts use -> PrusaSlicer's.
SETTINGS_MAP = {
    "wall_loops": "perimeters",
    "sparse_infill_density": "fill_density",
    "top_shell_layers": "top_solid_layers",
    "bottom_shell_layers": "bottom_solid_layers",
}

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
    ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
    "</Relationships>"
)


@dataclass(frozen=True)
class Written3mf:
    path: Path
    untranslated: tuple[str, ...] = ()
    # object name -> (x, y) of the footprint centre on the bed
    placements: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class _Mesh:
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]
    volumes: list[tuple[Part, int, int]]  # part, first and last triangle index


def _build(parts: list[Part]) -> _Mesh:
    mesh = _Mesh([], [], [])
    index: dict[tuple[float, float, float], int] = {}
    for part in parts:
        first = len(mesh.triangles)
        for tri in read_stl(part.stl):
            ids = []
            for vertex in tri:
                key = (round(vertex[0], 5), round(vertex[1], 5), round(vertex[2], 5))
                if key not in index:
                    index[key] = len(mesh.vertices)
                    mesh.vertices.append(key)
                ids.append(index[key])
            mesh.triangles.append((ids[0], ids[1], ids[2]))
        if len(mesh.triangles) == first:
            raise SlicerError(f"{part.stl} has no triangles")
        mesh.volumes.append((part, first, len(mesh.triangles) - 1))
    return mesh


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _shelves(sizes: list[tuple[float, float]], width: float) -> list[tuple[float, float]]:
    """Lower-left corners for footprints packed in rows from the origin, GAP_MM apart."""
    corners: list[tuple[float, float]] = []
    x = y = row_h = 0.0
    for w, h in sizes:
        if x > 0 and x + w > width:
            x, y, row_h = 0.0, y + row_h + GAP_MM, 0.0
        corners.append((x, y))
        x += w + GAP_MM
        row_h = max(row_h, h)
    return corners


def place(
    sizes: list[tuple[float, float]],
    bed: tuple[float, float, float],
    exclude: tuple[tuple[float, float, float, float], ...] = (),
) -> list[tuple[float, float]]:
    """Lower-left corner of each footprint on the bed: packed, group centred, checked."""
    corners = _shelves(sizes, bed[0] - 2 * MARGIN_MM)
    rects = [(cx, cy, cx + w, cy + h) for (cx, cy), (w, h) in zip(corners, sizes)]
    gw = max((r[2] for r in rects), default=0.0)
    gh = max((r[3] for r in rects), default=0.0)
    tried = []
    for ox, oy in ((bed[0] / 2 - gw / 2, bed[1] / 2 - gh / 2), (MARGIN_MM, MARGIN_MM)):
        shifted = [(r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy) for r in rects]
        bad = [
            r for r in shifted
            if r[0] < 0 or r[1] < 0 or r[2] > bed[0] or r[3] > bed[1] or any(_overlap(r, e) for e in exclude)
        ]
        if not bad:
            return [(r[0], r[1]) for r in shifted]
        tried.append(bad[0])
    raise SlicerError(
        f"Objects do not fit the {bed[0]:g} x {bed[1]:g} mm bed (excluded areas: {list(exclude) or 'none'}); "
        f"first footprint out of bounds: {tuple(round(v, 1) for v in tried[0])}."
    )


def write_3mf(
    objects: list[tuple[str, list[Part]]],
    bed: tuple[float, float, float],
    out: Path,
    exclude: tuple[tuple[float, float, float, float], ...] = (),
) -> Written3mf:
    """Write `objects` (name, parts) as one PrusaSlicer 3MF, dropped to z=0 and placed on the bed."""
    meshes = [_build(parts) for _, parts in objects]
    boxes = []
    for mesh in meshes:
        xs, ys, zs = zip(*mesh.vertices)
        boxes.append((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
    corners = place([(b[3] - b[0], b[4] - b[1]) for b in boxes], bed, exclude)
    top = max((b[5] - b[2] for b in boxes), default=0.0)
    if top > bed[2]:
        raise SlicerError(f"Object is {top:.1f} mm tall; the printer allows {bed[2]:g} mm.")

    untranslated: list[str] = []
    resources, items, configs = [], [], []
    placements: dict[str, tuple[float, float]] = {}
    for n, ((name, _), mesh, box, (cx, cy)) in enumerate(zip(objects, meshes, boxes, corners), start=1):
        mid_x, mid_y = (box[0] + box[3]) / 2, (box[1] + box[4]) / 2
        verts = "\n".join(
            f'     <vertex x="{x - mid_x:.5f}" y="{y - mid_y:.5f}" z="{z - box[2]:.5f}"/>'
            for x, y, z in mesh.vertices
        )
        tris = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.triangles)
        resources.append(
            f'  <object id="{n}" type="model">\n   <mesh>\n    <vertices>\n{verts}\n    </vertices>\n'
            f"    <triangles>\n{tris}\n    </triangles>\n   </mesh>\n  </object>"
        )
        px, py = cx + (box[3] - box[0]) / 2, cy + (box[4] - box[1]) / 2
        placements[name] = (round(px, 3), round(py, 3))
        items.append(f'  <item objectid="{n}" transform="1 0 0 0 1 0 0 0 1 {px:.4f} {py:.4f} 0" printable="1"/>')

        lines = [
            f' <object id="{n}" instances_count="1">',
            f'  <metadata type="object" key="name" value={quoteattr(name)}/>',
            f'  <metadata type="object" key="extruder" value="{mesh.volumes[0][0].tool}"/>',
        ]
        for part, first, last in mesh.volumes:
            lines += [
                f'  <volume firstid="{first}" lastid="{last}">',
                f'   <metadata type="volume" key="name" value={quoteattr(part.name)}/>',
                '   <metadata type="volume" key="volume_type" value="ModelPart"/>',
                f'   <metadata type="volume" key="matrix" value="{IDENTITY}"/>',
                f'   <metadata type="volume" key="extruder" value="{part.tool}"/>',
            ]
            for key, value in part.settings.items():
                mapped = SETTINGS_MAP.get(key)
                if mapped is None:
                    untranslated.append(key)
                lines.append(f'   <metadata type="volume" key="{mapped or key}" value={quoteattr(str(value))}/>')
            lines.append("  </volume>")
        lines.append(" </object>")
        configs.append("\n".join(lines))

    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n'
        ' <metadata name="slic3rpe:Version3mf">1</metadata>\n'
        ' <metadata name="Application">print3d</metadata>\n'
        " <resources>\n" + "\n".join(resources) + "\n </resources>\n"
        " <build>\n" + "\n".join(items) + "\n </build>\n</model>\n"
    )
    config = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(configs) + "\n</config>\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/Slic3r_PE_model.config", config)
    return Written3mf(out, tuple(dict.fromkeys(untranslated)), placements)
