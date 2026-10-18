"""LEGO-compatible 2x4 brick, driven by a spec measured off a photo.

Reference model script for the photo workflow: every number comes from
`params["dims"]`, recorded by `print3d measure`. The brick is solid; its studs
are the part a real brick has to grip, so they are what a test print checks.
"""

import bpy

d = params["dims"]
length, width, height = d["length"], d["width"], d["height"]
pitch = d["stud_span"] / 3
row_pitch = d["row_pitch"]
# The studs sit symmetrically, so their radius is what the margin leaves.
radius = (length - d["stud_span"]) / 2 - d["stud_margin"]
stud_h = d["stud_height"]
embed = 0.2

bpy.ops.mesh.primitive_cube_add(size=1)
body = bpy.context.active_object
body.scale = (length, width, height)
body.location.z = height / 2
bpy.ops.object.transform_apply(location=True, scale=True)

studs = []
for col in range(4):
    for row in range(2):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=radius, depth=stud_h + embed, vertices=64,
            location=((col - 1.5) * pitch, (row - 0.5) * row_pitch, height + (stud_h - embed) / 2),
        )
        studs.append(bpy.context.active_object)

# One boolean against all eight studs: join them first.
for stud in studs:
    stud.select_set(True)
bpy.context.view_layer.objects.active = studs[0]
bpy.ops.object.join()
stud_mesh = bpy.context.active_object

union = body.modifiers.new("studs", "BOOLEAN")
union.operation, union.object, union.solver = "UNION", stud_mesh, "EXACT"
bpy.context.view_layer.objects.active = body
bpy.ops.object.modifier_apply(modifier="studs")
bpy.data.objects.remove(stud_mesh, do_unlink=True)
