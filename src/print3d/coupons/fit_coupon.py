"""Fit coupon: one 8 mm pin and a plate of holes, each a little looser than the last.

Print it, then push the pin into each hole and note where it stops pressing in,
where it slides without play and where it turns loosely. The label next to each
hole is its clearance per side in hundredths of a millimetre. Record what you
felt with `print3d fit set --press 0.05 --snug 0.10 --slide 0.20 --free 0.35`.

Pin and holes both stand vertically, the way most printed fits are made.
The pin goes in shaft first; its flange is the handle.
"""

import bpy

PIN_D = 8.0
CLEARANCES = (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
PITCH = 17.0
COLS = 4
PLATE_T = 6.0
MARGIN = 6.0
LABEL_H = 0.6
SEGMENTS = 96


def solid(op, **kw):
    op(**kw)
    return bpy.context.active_object


def apply(target, other, operation):
    m = target.modifiers.new("b", "BOOLEAN")
    m.operation, m.object, m.solver = operation, other, "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier="b")
    bpy.data.objects.remove(other, do_unlink=True)


rows = (len(CLEARANCES) + COLS - 1) // COLS
width = COLS * PITCH + MARGIN
depth = rows * (PITCH + 5.0) + MARGIN
plate = solid(bpy.ops.mesh.primitive_cube_add, size=1)
plate.scale = (width, depth, PLATE_T)
bpy.ops.object.transform_apply(scale=True)
plate.location.z = PLATE_T / 2
bpy.ops.object.transform_apply(location=True)

for i, c in enumerate(CLEARANCES):
    row, col = divmod(i, COLS)
    x = -width / 2 + MARGIN / 2 + PITCH / 2 + col * PITCH
    y = depth / 2 - MARGIN / 2 - (PITCH + 5.0) / 2 - row * (PITCH + 5.0) + 2.5
    hole = solid(bpy.ops.mesh.primitive_cylinder_add, vertices=SEGMENTS,
                 radius=PIN_D / 2 + c, depth=PLATE_T + 2, location=(x, y, PLATE_T / 2))
    apply(plate, hole, "DIFFERENCE")

    label = solid(bpy.ops.object.text_add, location=(x, y - PIN_D / 2 - 4.2, 0))
    label.data.body = f"{round(c * 100):02d}"
    label.data.size = 4.0
    label.data.align_x, label.data.align_y = "CENTER", "CENTER"
    label.data.extrude = (LABEL_H + 0.2) / 2
    bpy.ops.object.convert(target="MESH")
    label.location.z = PLATE_T - 0.2 + (LABEL_H + 0.2) / 2
    apply(plate, label, "UNION")

pin = solid(bpy.ops.mesh.primitive_cylinder_add, vertices=SEGMENTS, radius=PIN_D / 2,
            depth=16.0, location=(width / 2 + 12.0, 0, 3.0 + 8.0 - 0.2))
# The pin stands on a grip flange: it holds the plate, and the first layer's
# squish lands on the flange instead of the surface being measured.
flange = solid(bpy.ops.mesh.primitive_cylinder_add, vertices=SEGMENTS, radius=7.0,
               depth=3.0, location=(width / 2 + 12.0, 0, 1.5))
apply(pin, flange, "UNION")
bevel = pin.modifiers.new("chamfer", "BEVEL")
bevel.width, bevel.segments, bevel.limit_method = 0.4, 1, "ANGLE"

part(plate, "holes")
part(pin, "pin")
