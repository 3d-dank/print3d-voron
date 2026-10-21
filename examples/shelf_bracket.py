"""Shelf bracket, rebuilt from its stated sizes and one photo.

Reference model script for the listing workflow: every number comes from
`params["dims"]`, quoted from the listing or measured off the photo it scaled.
It prints lying on its side, the strut flat on the bed: standing up, the long
leg would be a 200 mm overhang. The screw holes run sideways through the legs,
so they are teardrops, pointed up, to print without supports.
"""

import math

import bmesh
import bpy

d = params["dims"]
t, width = d["thickness"], d["width"]
# The listing rounds the short leg to the centimetre; the photo, scaled from the
# long leg, agrees with it and is tighter.
long_leg, short_leg = d["long_leg"], d["short_leg_measured"]
bend = d["bend_radius"]
bore = d["hole_bore"] / 2


def prism(name, outline, z0, z1):
    """A solid from a 2D outline in the bed plane, between two heights."""
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new((x, y, z0)) for x, y in outline])
    extruded = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in extruded["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=(0, 0, z1 - z0))
    # The boolean solver needs the normals pointing out before the harness ever sees the mesh.
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def arc(cx, cy, r, a0, a1, steps=16):
    return [(cx + r * math.cos(a), cy + r * math.sin(a))
            for a in (a0 + (a1 - a0) * i / steps for i in range(steps + 1))]


def boolean(target, operand, operation):
    m = target.modifiers.new(operation, "BOOLEAN")
    m.operation, m.object, m.solver = operation, operand, "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=operation)
    bpy.data.objects.remove(operand, do_unlink=True)


# The L, outer corner at the origin: the long leg runs along +x, the short one along -y.
outline = (
    [(0, -short_leg)]
    + arc(bend, -bend, bend, math.pi, math.pi / 2)
    + [(long_leg, 0), (long_leg, -t)]
    + arc(bend, -bend, bend - t, math.pi / 2, math.pi)
    + [(t, -short_leg)]
)
bracket = prism("bracket", outline, 0, width)

# The strut: a plate of the same stock, flat on the bed, sunk into both legs.
sink = 0.2
strut = prism("strut", [
    (t - sink, -d["strut_wall_top"]), (d["strut_shelf_top"], -t + sink),
    (d["strut_shelf_bottom"], -t + sink), (t - sink, -d["strut_wall_bottom"]),
], 0, t)
boolean(bracket, strut, "UNION")

# Screw holes through the legs, at half the width. A teardrop's flanks rise at 51 degrees.
apex = bore * 1.6
tangent = math.acos(bore / apex)
drop = [(0, apex)] + arc(0, 0, bore, math.pi / 2 + tangent, 2.5 * math.pi - tangent)
for name, along, on_long_leg in [
    ("hole_shelf_1", d["hole_shelf_1"], True), ("hole_shelf_2", d["hole_shelf_2"], True),
    ("hole_shelf_3", d["hole_shelf_3"], True),
    ("hole_wall_1", d["hole_wall_1"], False), ("hole_wall_2", d["hole_wall_2"], False),
]:
    # Drawn in the bed plane, then stood up across the leg it goes through.
    hole = prism(name, drop, -1, t + 1)
    hole.rotation_euler = (math.pi / 2, 0, 0) if on_long_leg else (math.pi / 2, 0, math.pi / 2)
    hole.location = (along, 0, width / 2) if on_long_leg else (0, -along, width / 2)
    bpy.context.view_layer.objects.active = hole
    bpy.ops.object.transform_apply(location=True, rotation=True)
    boolean(bracket, hole, "DIFFERENCE")
