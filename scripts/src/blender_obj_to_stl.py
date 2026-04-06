import argparse
import sys
from pathlib import Path

import bmesh
import bpy


FORWARD_AXIS = "Y"
UP_AXIS = "Z"


def parse_bool(value):
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise argparse.ArgumentTypeError(
        f"Expected a boolean value, got {value!r}. Use true/false."
    )


def parse_blender_args():
    if "--" not in sys.argv:
        raise SystemExit(
            "Usage: blender --background --python blender_obj_to_stl.py -- input.obj output.stl")

    # Extract arguments after "--"
    argv = sys.argv[sys.argv.index("--") + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("input_obj", type=Path)
    parser.add_argument("output_stl", type=Path)
    parser.add_argument("--processed-obj", "--processed_obj",
                        dest="processed_obj", type=Path, default=None)
    parser.add_argument("--remove-internal-voids", "--remove_internal_voids",
                        dest="remove_internal_voids", type=parse_bool,
                        nargs="?", const=True, default=True)
    parser.add_argument("--internal-void-volume-epsilon", "--internal_void_volume_epsilon",
                        dest="internal_void_volume_epsilon", type=float, default=1e-6)
    parser.add_argument("--fix-inverted-normals", "--fix_inverted_normals",
                        dest="fix_inverted_normals", type=parse_bool,
                        nargs="?", const=True, default=True)
    parser.add_argument("--normal-volume-epsilon", "--normal_volume_epsilon",
                        dest="normal_volume_epsilon", type=float, default=1e-6)
    parser.add_argument("--smooth-mesh", "--smooth_mesh",
                        dest="smooth_mesh", type=parse_bool,
                        nargs="?", const=True, default=False)
    parser.add_argument("--smooth-repeat", "--smooth_repeat",
                        dest="smooth_repeat", type=int, default=1)
    parser.add_argument("--smooth-lambda-factor", "--smooth_lambda_factor",
                        dest="smooth_lambda_factor", type=float, default=0.5)
    parser.add_argument("--smooth-lambda-border", "--smooth_lambda_border",
                        dest="smooth_lambda_border", type=float, default=0.5)
    parser.add_argument("--smooth-preserve-volume", "--smooth_preserve_volume",
                        dest="smooth_preserve_volume", type=parse_bool,
                        nargs="?", const=True, default=True)
    parser.add_argument("--decimate-mesh", "--decimate_mesh",
                        dest="decimate_mesh", type=parse_bool,
                        nargs="?", const=True, default=False)
    parser.add_argument("--decimate-ratio", "--decimate_ratio",
                        dest="decimate_ratio", type=float, default=1.0)
    parser.add_argument("--decimate-max-faces", "--decimate_max_faces",
                        dest="decimate_max_faces", type=int, default=0)

    args = parser.parse_args(argv)
    args.input_obj = args.input_obj.resolve()
    args.output_stl = args.output_stl.resolve()
    if args.processed_obj is not None:
        args.processed_obj = args.processed_obj.resolve()
    return args


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_obj(path: Path):
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(
            filepath=str(path),
            forward_axis=FORWARD_AXIS,
            up_axis=UP_AXIS,
        )
    else:
        bpy.ops.import_scene.obj(
            filepath=str(path),
            axis_forward=FORWARD_AXIS,
            axis_up=UP_AXIS,
        )


def select_mesh_objects():
    mesh_objects = [
        obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("No mesh objects were imported from OBJ.")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]

    return mesh_objects


def separate_loose_mesh_islands(objects):
    for obj in list(objects):
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")

    return select_mesh_objects()


def signed_mesh_volume(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        for vert in bm.verts:
            vert.co = obj.matrix_world @ vert.co
        return bm.calc_volume(signed=True)
    finally:
        bm.free()
        evaluated.to_mesh_clear()


def flip_mesh_normals(obj):
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()

    mesh.update()


def remove_internal_voids(objects, volume_epsilon):
    island_objects = separate_loose_mesh_islands(objects)
    volumes = [(obj, signed_mesh_volume(obj)) for obj in island_objects]
    reference = max(volumes, key=lambda item: abs(item[1]), default=None)
    if reference is None or abs(reference[1]) <= volume_epsilon:
        return island_objects, []

    reference_sign = 1 if reference[1] > 0 else -1
    removed = []

    for obj, volume in volumes:
        if volume * reference_sign < -volume_epsilon:
            removed.append((obj.name, volume))
            bpy.data.objects.remove(obj, do_unlink=True)

    remaining_objects = select_mesh_objects()
    if not remaining_objects:
        raise RuntimeError("All mesh islands were removed as internal voids.")

    return remaining_objects, removed


def fix_inverted_normals(objects, volume_epsilon):
    island_objects = separate_loose_mesh_islands(objects)
    flipped = []

    for obj in island_objects:
        volume = signed_mesh_volume(obj)
        if volume < -volume_epsilon:
            flip_mesh_normals(obj)
            flipped.append((obj.name, volume, signed_mesh_volume(obj)))

    return select_mesh_objects(), flipped


def smooth_mesh_objects(
    objects,
    repeat,
    lambda_factor,
    lambda_border,
    preserve_volume,
):
    if repeat < 1:
        return 0, 0.0, 0.0

    lambda_factor = max(0.0, min(lambda_factor, 1.0))
    lambda_border = max(0.0, min(lambda_border, 1.0))

    def build_adjacency(mesh):
        neighbors = [set() for _ in mesh.vertices]
        edge_face_counts = {}
        for poly in mesh.polygons:
            ids = list(poly.vertices)
            for i, a in enumerate(ids):
                b = ids[(i + 1) % len(ids)]
                key = tuple(sorted((a, b)))
                edge_face_counts[key] = edge_face_counts.get(key, 0) + 1

        for a, b in edge_face_counts:
            neighbors[a].add(b)
            neighbors[b].add(a)

        boundary_vertices = set()
        for (a, b), count in edge_face_counts.items():
            if count == 1:
                boundary_vertices.add(a)
                boundary_vertices.add(b)

        return neighbors, boundary_vertices

    def apply_smooth_pass(mesh, neighbors, boundary_vertices, factor, border_factor):
        old_positions = [vert.co.copy() for vert in mesh.vertices]
        for index, vert in enumerate(mesh.vertices):
            linked = neighbors[index]
            if not linked:
                continue

            vertex_factor = border_factor if index in boundary_vertices else factor
            if vertex_factor == 0:
                continue

            average = sum((old_positions[i]
                          for i in linked), old_positions[index] * 0)
            average /= len(linked)
            vert.co = old_positions[index] + \
                (average - old_positions[index]) * vertex_factor

    def mesh_centroid(mesh):
        if not mesh.vertices:
            return None

        total = sum((vert.co for vert in mesh.vertices),
                    mesh.vertices[0].co * 0)
        return total / len(mesh.vertices)

    def local_signed_volume(mesh):
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            return bm.calc_volume(signed=True)
        finally:
            bm.free()

    def restore_volume(mesh, target_volume):
        current_volume = local_signed_volume(mesh)
        if abs(target_volume) <= 1e-15 or abs(current_volume) <= 1e-15:
            return
        if target_volume * current_volume <= 0:
            return

        centroid = mesh_centroid(mesh)
        if centroid is None:
            return

        scale = abs(target_volume / current_volume) ** (1.0 / 3.0)
        for vert in mesh.vertices:
            vert.co = centroid + (vert.co - centroid) * scale

    smoothed = 0
    max_delta = 0.0
    total_delta = 0.0
    total_vertices = 0
    for obj in list(objects):
        mesh = obj.data
        before_positions = [vert.co.copy() for vert in mesh.vertices]
        target_volume = local_signed_volume(mesh) if preserve_volume else None
        neighbors, boundary_vertices = build_adjacency(mesh)
        for _ in range(repeat):
            apply_smooth_pass(
                mesh,
                neighbors,
                boundary_vertices,
                lambda_factor,
                lambda_border,
            )
        if preserve_volume:
            restore_volume(mesh, target_volume)
        mesh.update()
        deltas = [
            (vert.co - before_positions[index]).length
            for index, vert in enumerate(mesh.vertices)
        ]
        if deltas:
            max_delta = max(max_delta, max(deltas))
            total_delta += sum(deltas)
            total_vertices += len(deltas)
        smoothed += 1

    average_delta = total_delta / total_vertices if total_vertices else 0.0
    return smoothed, max_delta, average_delta


def decimate_mesh_objects(objects, ratio, max_faces):
    ratio = max(0.01, min(ratio, 1.0))
    decimated = []

    for obj in list(objects):
        before_faces = len(obj.data.polygons)
        if before_faces == 0:
            continue

        object_ratio = ratio
        if max_faces > 0 and before_faces > max_faces:
            object_ratio = min(object_ratio, max_faces / before_faces)

        if object_ratio >= 0.999:
            continue

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        modifier = obj.modifiers.new(
            name="collision_decimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = object_ratio
        modifier.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        after_faces = len(obj.data.polygons)
        decimated.append((obj.name, before_faces, after_faces, object_ratio))

    return select_mesh_objects(), decimated


def export_stl(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    # Try newer wm.stl_export API (Blender 4.2+)
    if hasattr(bpy.ops.wm, "stl_export"):
        try:
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True,
                forward_axis=FORWARD_AXIS,
                up_axis=UP_AXIS,
            )
            return
        except TypeError:
            # Fallback for slightly different wm.stl_export parameters
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True
            )
            return

    # Fallback for older export_mesh.stl API (Pre-4.2)
    try:
        bpy.ops.export_mesh.stl(
            filepath=str(path),
            use_selection=True,
            ascii=False,
            axis_forward=FORWARD_AXIS,
            axis_up=UP_AXIS,
        )
    except TypeError:
        bpy.ops.export_mesh.stl(
            filepath=str(path),
            use_selection=True,
            axis_forward=FORWARD_AXIS,
            axis_up=UP_AXIS,
        )


def export_obj(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(bpy.ops.wm, "obj_export"):
        bpy.ops.wm.obj_export(
            filepath=str(path),
            export_selected_objects=True,
            export_normals=True,
            export_materials=False,
            forward_axis=FORWARD_AXIS,
            up_axis=UP_AXIS,
        )
        return

    bpy.ops.export_scene.obj(
        filepath=str(path),
        use_selection=True,
        use_normals=True,
        use_materials=False,
        axis_forward=FORWARD_AXIS,
        axis_up=UP_AXIS,
    )


def main():
    args = parse_blender_args()
    input_obj = args.input_obj
    output_stl = args.output_stl
    if not input_obj.is_file():
        raise SystemExit(f"Input OBJ does not exist: {input_obj}")

    clear_scene()
    import_obj(input_obj)
    mesh_objects = select_mesh_objects()
    removed_voids = []
    flipped_normals = []
    smoothed_count = 0
    smooth_max_delta = 0.0
    smooth_average_delta = 0.0
    decimated = []

    if args.remove_internal_voids:
        mesh_objects, removed_voids = remove_internal_voids(
            mesh_objects,
            volume_epsilon=args.internal_void_volume_epsilon,
        )
    if args.fix_inverted_normals:
        mesh_objects, flipped_normals = fix_inverted_normals(
            mesh_objects,
            volume_epsilon=args.normal_volume_epsilon,
        )
    if args.smooth_mesh:
        smoothed_count, smooth_max_delta, smooth_average_delta = smooth_mesh_objects(
            mesh_objects,
            repeat=args.smooth_repeat,
            lambda_factor=args.smooth_lambda_factor,
            lambda_border=args.smooth_lambda_border,
            preserve_volume=args.smooth_preserve_volume,
        )
    if args.decimate_mesh:
        mesh_objects, decimated = decimate_mesh_objects(
            mesh_objects,
            ratio=args.decimate_ratio,
            max_faces=args.decimate_max_faces,
        )
    if args.processed_obj is not None:
        export_obj(args.processed_obj)
    export_stl(output_stl)

    # Logging results
    print(f"[INFO] Imported OBJ: {input_obj}")
    print(f"[INFO] Mesh object count: {len(mesh_objects)}")
    if args.remove_internal_voids:
        print(f"[INFO] Removed internal void islands: {len(removed_voids)}")
        for name, volume in removed_voids:
            print(f"[INFO]   - {name}: signed_volume={volume:.10g}")
    if args.fix_inverted_normals:
        print(f"[INFO] Fixed inverted-normal islands: {len(flipped_normals)}")
        for name, old_volume, new_volume in flipped_normals:
            print(
                "[INFO]   - "
                f"{name}: signed_volume={old_volume:.10g} -> {new_volume:.10g}"
            )
    if args.smooth_mesh:
        print(
            "[INFO] Smoothed mesh objects: "
            f"{smoothed_count}, repeat={args.smooth_repeat}, "
            f"lambda_factor={args.smooth_lambda_factor}, "
            f"preserve_volume={args.smooth_preserve_volume}, "
            f"max_delta={smooth_max_delta:.10g}, "
            f"avg_delta={smooth_average_delta:.10g}"
        )
    if args.decimate_mesh:
        total_before = sum(item[1] for item in decimated)
        total_after = sum(item[2] for item in decimated)
        print(
            "[INFO] Decimated mesh objects: "
            f"{len(decimated)}, faces={total_before}->{total_after}"
        )
        for name, before_faces, after_faces, object_ratio in decimated:
            print(
                "[INFO]   - "
                f"{name}: faces={before_faces}->{after_faces}, "
                f"ratio={object_ratio:.10g}"
            )
    if args.processed_obj is not None:
        print(f"[INFO] Exported processed OBJ: {args.processed_obj}")
    print(f"[INFO] Exported STL: {output_stl}")


if __name__ == "__main__":
    main()
