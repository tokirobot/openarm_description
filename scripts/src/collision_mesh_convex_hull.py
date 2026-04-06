import argparse
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


SUPPORTED_INPUTS = {".dae", ".obj", ".stl"}


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Build one STL collision mesh from an input mesh using Blender convex hull."
    )
    parser.add_argument("input_mesh", type=Path)
    parser.add_argument("output_stl", type=Path)
    parser.add_argument(
        "--per-node-hull",
        action="store_true",
        help=(
            "Apply convex hull to each imported mesh object first, then join "
            "the hulls into one exported STL. Useful for DAE files with multiple nodes."
        ),
    )
    parser.add_argument(
        "--split-axis",
        choices=("x", "y", "z", "X", "Y", "Z"),
        default=None,
        help=(
            "Cut the joined mesh by a plane perpendicular to this axis before "
            "building hulls. Requires --split-direction and --split-offset."
        ),
    )
    parser.add_argument(
        "--split-direction",
        choices=("positive", "negative", "pos", "neg", "+", "-"),
        default=None,
        help=(
            "Side whose farthest point is used as the cut origin. For example, "
            "positive with --split-axis x starts from max X and offsets inward."
        ),
    )
    parser.add_argument(
        "--split-offset",
        type=float,
        default=None,
        help=(
            "Distance from the selected axis extreme toward the model interior "
            "where the cut plane is placed."
        ),
    )
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_mesh(path: Path):
    suffix = path.suffix.lower()

    if suffix == ".dae":
        if not hasattr(bpy.ops.wm, "collada_import"):
            raise RuntimeError(
                "This Blender build does not provide Collada import.")
        bpy.ops.wm.collada_import(filepath=str(path), import_units=True)
        return

    if suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
        return

    if suffix == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.stl(filepath=str(path))
        return

    raise RuntimeError(f"Unsupported input mesh format: {path.suffix}")


def convert_convertible_objects_to_mesh():
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CURVE", "SURFACE", "FONT"}:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.convert(target="MESH")


def mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def join_mesh_objects(objects, name):
    if not objects:
        raise RuntimeError("No mesh objects were imported.")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if len(objects) > 1:
        bpy.ops.object.join()

    joined = bpy.context.view_layer.objects.active
    joined.name = name
    joined.data.name = f"{name}_mesh"
    return joined


def clean_mesh_object(obj):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.delete_loose()
    try:
        bpy.ops.mesh.dissolve_degenerate()
    except Exception:
        pass
    bpy.ops.object.mode_set(mode="OBJECT")


def apply_convex_hull(obj):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.convex_hull(
            delete_unused=True,
            use_existing_faces=False,
            make_holes=False,
            join_triangles=True,
        )
    except TypeError:
        bpy.ops.mesh.convex_hull(delete_unused=True)

    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    except Exception:
        pass
    bpy.ops.object.mode_set(mode="OBJECT")


def apply_convex_hulls_per_object(objects):
    for obj in objects:
        obj.data = obj.data.copy()
        clean_mesh_object(obj)
        apply_convex_hull(obj)


def parse_split_direction(raw):
    if raw in {"positive", "pos", "+"}:
        return 1
    if raw in {"negative", "neg", "-"}:
        return -1
    raise ValueError(f"Unsupported split direction: {raw}")


def validate_split_args(args):
    values = [
        args.split_axis is not None,
        args.split_direction is not None,
        args.split_offset is not None,
    ]
    if any(values) and not all(values):
        raise SystemExit(
            "--split-axis, --split-direction, and --split-offset must be used together."
        )
    if args.split_axis is None:
        return False
    if args.per_node_hull:
        raise SystemExit("--per-node-hull cannot be combined with split cutting.")
    if args.split_offset <= 0:
        raise SystemExit("--split-offset must be greater than 0.")
    return True


def mesh_axis_bounds(obj, axis_index):
    coords = [vertex.co[axis_index] for vertex in obj.data.vertices]
    if not coords:
        raise RuntimeError(f"Object has no vertices: {obj.name}")
    return min(coords), max(coords)


def split_output_paths(output_stl: Path, axis, direction_sign):
    direction_label = "pos" if direction_sign > 0 else "neg"
    label = f"split_{direction_label}_{axis}"
    return {
        "far_raw": output_stl.with_name(f"{output_stl.stem}_{label}_far_raw.stl"),
        "inner_raw": output_stl.with_name(f"{output_stl.stem}_{label}_inner_raw.stl"),
        "far_hull": output_stl.with_name(f"{output_stl.stem}_{label}_far_hull.stl"),
        "inner_hull": output_stl.with_name(f"{output_stl.stem}_{label}_inner_hull.stl"),
    }


def duplicate_mesh_object(obj, name):
    duplicate = obj.copy()
    duplicate.data = obj.data.copy()
    duplicate.name = name
    duplicate.data.name = f"{name}_mesh"
    bpy.context.collection.objects.link(duplicate)
    return duplicate


def bisect_object_by_axis(obj, axis_index, plane_coord, direction_sign, keep_far_side):
    axis_vector = [0.0, 0.0, 0.0]
    axis_vector[axis_index] = float(direction_sign)
    plane_point = [0.0, 0.0, 0.0]
    plane_point[axis_index] = plane_coord

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(
            bm,
            geom=geom,
            plane_co=Vector(plane_point),
            plane_no=Vector(axis_vector),
            clear_inner=keep_far_side,
            clear_outer=not keep_far_side,
        )
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()


def ensure_non_empty_mesh(obj, label):
    if len(obj.data.vertices) == 0 or len(obj.data.polygons) == 0:
        raise RuntimeError(f"{label} split produced an empty mesh.")


def build_split_convex_hulls(joined, output_stl: Path, axis, direction_sign, offset):
    axis_index = {"x": 0, "y": 1, "z": 2}[axis]
    min_coord, max_coord = mesh_axis_bounds(joined, axis_index)
    extreme = max_coord if direction_sign > 0 else min_coord
    plane_coord = extreme - direction_sign * offset
    if not (min_coord < plane_coord < max_coord):
        raise RuntimeError(
            "Split plane is outside the mesh bounds: "
            f"axis={axis}, direction={'positive' if direction_sign > 0 else 'negative'}, "
            f"offset={offset:.10g}, bounds=({min_coord:.10g}, {max_coord:.10g}), "
            f"plane={plane_coord:.10g}"
        )

    paths = split_output_paths(output_stl, axis, direction_sign)
    far = duplicate_mesh_object(joined, f"{joined.name}_split_far")
    inner = duplicate_mesh_object(joined, f"{joined.name}_split_inner")

    bisect_object_by_axis(
        far,
        axis_index=axis_index,
        plane_coord=plane_coord,
        direction_sign=direction_sign,
        keep_far_side=True,
    )
    bisect_object_by_axis(
        inner,
        axis_index=axis_index,
        plane_coord=plane_coord,
        direction_sign=direction_sign,
        keep_far_side=False,
    )

    for label, obj in (("far", far), ("inner", inner)):
        clean_mesh_object(obj)
        ensure_non_empty_mesh(obj, label)

    export_stl(far, paths["far_raw"])
    export_stl(inner, paths["inner_raw"])

    apply_convex_hull(far)
    apply_convex_hull(inner)

    export_stl(far, paths["far_hull"])
    export_stl(inner, paths["inner_hull"])

    joined_hulls = join_mesh_objects(
        [far, inner],
        f"{joined.name}_split_joined_hulls",
    )
    export_stl(joined_hulls, output_stl)

    return {
        "axis": axis,
        "direction": "positive" if direction_sign > 0 else "negative",
        "offset": offset,
        "bounds": (min_coord, max_coord),
        "plane": plane_coord,
        "paths": paths,
    }


def export_stl(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if hasattr(bpy.ops.wm, "stl_export"):
        try:
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True,
                ascii_format=False,
            )
            return
        except TypeError:
            bpy.ops.wm.stl_export(filepath=str(
                path), export_selected_objects=True)
            return

    try:
        bpy.ops.export_mesh.stl(filepath=str(
            path), use_selection=True, ascii=False)
    except TypeError:
        bpy.ops.export_mesh.stl(filepath=str(path), use_selection=True)


def main():
    args = parse_args()
    input_mesh = args.input_mesh.resolve()
    output_stl = args.output_stl.resolve()
    split_enabled = validate_split_args(args)

    if not input_mesh.is_file():
        raise SystemExit(f"Input mesh does not exist: {input_mesh}")
    if input_mesh.suffix.lower() not in SUPPORTED_INPUTS:
        raise SystemExit(f"Unsupported input mesh format: {input_mesh.suffix}")

    clear_scene()
    import_mesh(input_mesh)
    convert_convertible_objects_to_mesh()

    objects = mesh_objects()

    split_info = None
    if split_enabled:
        axis = args.split_axis.lower()
        direction_sign = parse_split_direction(args.split_direction)
        joined = join_mesh_objects(objects, input_mesh.stem + "_split_source")
        clean_mesh_object(joined)
        split_info = build_split_convex_hulls(
            joined,
            output_stl,
            axis=axis,
            direction_sign=direction_sign,
            offset=args.split_offset,
        )
        hull = bpy.context.view_layer.objects.active
    elif args.per_node_hull:
        apply_convex_hulls_per_object(objects)
        hull = join_mesh_objects(
            objects, input_mesh.stem + "_per_node_convex_hull")
    else:
        hull = join_mesh_objects(objects, input_mesh.stem + "_convex_hull")
        clean_mesh_object(hull)
        apply_convex_hull(hull)

    if not split_enabled:
        export_stl(hull, output_stl)

    print(f"[INFO] Input mesh: {input_mesh}")
    print(f"[INFO] Source mesh objects: {len(objects)}")
    print(f"[INFO] Per-node hull: {args.per_node_hull}")
    print(f"[INFO] Output STL: {output_stl}")
    if split_info:
        print(
            "[INFO] Split cut: "
            f"axis={split_info['axis']}, "
            f"direction={split_info['direction']}, "
            f"offset={split_info['offset']:.10g}, "
            f"plane={split_info['plane']:.10g}, "
            f"bounds=({split_info['bounds'][0]:.10g}, "
            f"{split_info['bounds'][1]:.10g})"
        )
        for label, path in split_info["paths"].items():
            print(f"[INFO] Split output {label}: {path}")


if __name__ == "__main__":
    main()
