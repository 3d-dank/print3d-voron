"""Dolly peg, turned from a profile measured off a museum photo.

Reference model script for the photo workflow: every number comes from
`params["dims"]`, recorded by `print3d measure`. It prints standing on its knob;
lying down, the round underside would be one long overhang.
"""

import math

import bmesh
import bpy

d = params["dims"]
length, chamfer = d["length"], d["chamfer"]
knob, neck, body = d["knob_diameter"] / 2, d["neck_diameter"] / 2, d["body_diameter"] / 2

# The turned profile, (radius, height) from the knob up, closed on the axis at both ends.
profile = [
    (0, 0), (knob - chamfer, 0), (knob, chamfer), (knob, d["knob_length"]),
    (neck, d["knob_length"]), (neck, d["neck_at"]), (body, d["body_at"]),
    (body, length - chamfer), (body - chamfer, length), (0, length),
]
bm = bmesh.new()
verts = [bm.verts.new((r, 0, z)) for r, z in profile]
edges = [bm.edges.new(pair) for pair in zip(verts, verts[1:])]
bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1),
               angle=2 * math.pi, steps=96, use_merge=True)
mesh = bpy.data.meshes.new("peg")
bm.to_mesh(mesh)
bm.free()
peg = bpy.data.objects.new("peg", mesh)
bpy.context.collection.objects.link(peg)

# The slot: through the peg along y, open at the top, as wide as measured.
bpy.ops.mesh.primitive_cube_add(size=1)
slot = bpy.context.active_object
slot.scale = (d["slot_width"], 2 * body + 2, d["slot_length"] + 1)
slot.location = (0, 0, length - d["slot_length"] + (d["slot_length"] + 1) / 2)
bpy.ops.object.transform_apply(location=True, scale=True)

cut = peg.modifiers.new("slot", "BOOLEAN")
cut.operation, cut.object, cut.solver = "DIFFERENCE", slot, "EXACT"
bpy.context.view_layer.objects.active = peg
bpy.ops.object.modifier_apply(modifier="slot")
bpy.data.objects.remove(slot, do_unlink=True)
