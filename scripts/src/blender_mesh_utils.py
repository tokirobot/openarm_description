from pathlib import Path

import bmesh
import bpy
from mathutils.bvhtree import BVHTree


FORWARD_AXIS = "Y"
UP_AXIS = "Z"
SUPPORTED_INPUTS = {".stl", ".obj", ".dae", ".ply"}
SUPPORTED_OUTPUTS = {".stl", ".obj"}
SUPPORTED_TOOL_MESHES = {".stl", ".obj"}


def parse_bool(value):
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"Expected a boolean value, got {value!r}.")


def parse_mesh_extensions(raw, supported=None):
    supported = SUPPORTED_TOOL_MESHES if supported is None else supported
    extensions = []
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = "." + item
        if item not in supported:
            raise ValueError(f"Unsupported extension: {item}")
        extensions.append(item)

    if not extensions:
        raise ValueError("At least one extension is required.")

    return tuple(dict.fromkeys(extensions))


def path_is_relative_to(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def iter_mesh_inputs(input_path, recursive, extensions, output_root=None):
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_TOOL_MESHES:
            raise ValueError(f"Unsupported input mesh format: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path does not exist: {input_path}")

    pattern = "**/*" if recursive else "*"
    meshes = []
    for path in sorted(input_path.glob(pattern)):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        if output_root is not None and path_is_relative_to(path.resolve(), output_root):
            continue
        meshes.append(path)

    if not meshes:
        raise ValueError(f"No mesh files found under: {input_path}")

    return meshes


def output_path_for_input(input_mesh, input_root, output_path):
    if input_root is None:
        return output_path
    return output_path / input_mesh.relative_to(input_root)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_mesh(path: Path):
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_INPUTS:
        raise RuntimeError(f"Unsupported input mesh format: {path.suffix}")

    if suffix == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.stl(filepath=str(path))
        return

    if suffix == ".obj":
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
        return

    if suffix == ".dae":
        if not hasattr(bpy.ops.wm, "collada_import"):
            raise RuntimeError("This Blender build does not provide Collada import.")
        bpy.ops.wm.collada_import(filepath=str(path), import_units=True)
        return

    if suffix == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.ply(filepath=str(path))


def mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def ensure_object_mode():
    active = bpy.context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def select_mesh_objects():
    objects = mesh_objects()
    if not objects:
        raise RuntimeError("No mesh objects are present.")
    ensure_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    return objects


def set_active(obj):
    ensure_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def join_mesh_objects(objects, name="joined_mesh"):
    if not objects:
        raise RuntimeError("No mesh objects to join.")

    ensure_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if len(objects) > 1:
        bpy.ops.object.join()

    joined = bpy.context.view_layer.objects.active
    joined.name = name
    joined.data.name = f"{name}_data"
    return joined


def separate_loose_mesh_islands(objects):
    for obj in list(objects):
        set_active(obj)
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

    remaining = select_mesh_objects()
    if not remaining:
        raise RuntimeError("All mesh islands were removed as internal voids.")
    return remaining, removed


def fix_inverted_normals(objects, volume_epsilon):
    island_objects = separate_loose_mesh_islands(objects)
    flipped = []
    for obj in island_objects:
        volume = signed_mesh_volume(obj)
        if volume < -volume_epsilon:
            flip_mesh_normals(obj)
            flipped.append((obj.name, volume, signed_mesh_volume(obj)))
    return select_mesh_objects(), flipped


def boundary_edge_count(mesh):
    edge_face_counts = {}
    for poly in mesh.polygons:
        ids = list(poly.vertices)
        for index, a in enumerate(ids):
            b = ids[(index + 1) % len(ids)]
            key = tuple(sorted((a, b)))
            edge_face_counts[key] = edge_face_counts.get(key, 0) + 1
    return sum(1 for count in edge_face_counts.values() if count == 1)


def _segment_triangle_intersection(
    point_a,
    point_b,
    tri_a,
    tri_b,
    tri_c,
    epsilon,
):
    direction = point_b - point_a
    edge_1 = tri_b - tri_a
    edge_2 = tri_c - tri_a
    h = direction.cross(edge_2)
    determinant = edge_1.dot(h)
    if abs(determinant) < epsilon:
        return False

    inverse = 1.0 / determinant
    s = point_a - tri_a
    u = inverse * s.dot(h)
    if u < -epsilon or u > 1.0 + epsilon:
        return False

    q = s.cross(edge_1)
    v = inverse * direction.dot(q)
    if v < -epsilon or u + v > 1.0 + epsilon:
        return False

    t = inverse * edge_2.dot(q)
    return -epsilon <= t <= 1.0 + epsilon


def _triangles_intersect(triangle_a, triangle_b, epsilon):
    for index in range(3):
        if _segment_triangle_intersection(
            triangle_a[index],
            triangle_a[(index + 1) % 3],
            triangle_b[0],
            triangle_b[1],
            triangle_b[2],
            epsilon,
        ):
            return True
        if _segment_triangle_intersection(
            triangle_b[index],
            triangle_b[(index + 1) % 3],
            triangle_a[0],
            triangle_a[1],
            triangle_a[2],
            epsilon,
        ):
            return True

    return False


def self_intersection_summary(
    objects,
    bvh_epsilon=1e-9,
    intersection_epsilon=1e-10,
):
    reports = []
    total_pairs = 0
    total_faces = 0

    for obj in objects:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            if any(len(face.verts) != 3 for face in bm.faces):
                bmesh.ops.triangulate(bm, faces=list(bm.faces))

            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            for vert in bm.verts:
                vert.co = obj.matrix_world @ vert.co

            tree = BVHTree.FromBMesh(bm, epsilon=bvh_epsilon)
            vertices = [vert.co.copy() for vert in bm.verts]
            faces = [[vert.index for vert in face.verts] for face in bm.faces]
            face_vertex_sets = [set(face) for face in faces]

            intersecting_pairs = 0
            intersecting_faces = set()
            for face_a, face_b in tree.overlap(tree):
                if face_a >= face_b:
                    continue
                if not face_vertex_sets[face_a].isdisjoint(
                    face_vertex_sets[face_b]
                ):
                    continue

                triangle_a = [vertices[index] for index in faces[face_a]]
                triangle_b = [vertices[index] for index in faces[face_b]]
                if _triangles_intersect(
                    triangle_a,
                    triangle_b,
                    intersection_epsilon,
                ):
                    intersecting_pairs += 1
                    intersecting_faces.update((face_a, face_b))

            total_pairs += intersecting_pairs
            total_faces += len(intersecting_faces)
            reports.append(
                {
                    "object": obj.name,
                    "faces": len(faces),
                    "self_intersection_pairs": intersecting_pairs,
                    "self_intersection_faces": len(intersecting_faces),
                }
            )
        finally:
            bm.free()
            evaluated.to_mesh_clear()

    return {
        "objects": reports,
        "self_intersection_pairs": total_pairs,
        "self_intersection_faces": total_faces,
    }


def clean_mesh_object(
    obj,
    delete_loose=True,
    dissolve_degenerate=True,
    merge_distance=0.0,
    fill_holes=False,
    hole_sides=0,
    recalc_normals=False,
):
    before = mesh_summary([obj])
    set_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")

    if delete_loose:
        bpy.ops.mesh.delete_loose()
        bpy.ops.mesh.select_all(action="SELECT")

    if merge_distance > 0:
        try:
            bpy.ops.mesh.remove_doubles(threshold=merge_distance)
        except TypeError:
            bpy.ops.mesh.remove_doubles()
        bpy.ops.mesh.select_all(action="SELECT")

    if dissolve_degenerate:
        try:
            bpy.ops.mesh.dissolve_degenerate()
        except Exception:
            pass
        bpy.ops.mesh.select_all(action="SELECT")

    if fill_holes:
        try:
            bpy.ops.mesh.fill_holes(sides=hole_sides)
        except TypeError:
            bpy.ops.mesh.fill_holes()
        bpy.ops.mesh.select_all(action="SELECT")

    if recalc_normals:
        try:
            bpy.ops.mesh.normals_make_consistent(inside=False)
        except Exception:
            pass

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.update()
    after = mesh_summary([obj])
    return before, after


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
            for index, a in enumerate(ids):
                b = ids[(index + 1) % len(ids)]
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
            average = sum((old_positions[i] for i in linked), old_positions[index] * 0)
            average /= len(linked)
            vert.co = old_positions[index] + (average - old_positions[index]) * vertex_factor

    def mesh_centroid(mesh):
        if not mesh.vertices:
            return None
        total = sum((vert.co for vert in mesh.vertices), mesh.vertices[0].co * 0)
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
            apply_smooth_pass(mesh, neighbors, boundary_vertices, lambda_factor, lambda_border)
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

        set_active(obj)
        modifier = obj.modifiers.new(name="mesh_decimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = object_ratio
        modifier.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        after_faces = len(obj.data.polygons)
        decimated.append((obj.name, before_faces, after_faces, object_ratio))

    return select_mesh_objects(), decimated


def triangulate_objects(objects):
    for obj in objects:
        set_active(obj)
        modifier = obj.modifiers.new(name="triangulate_for_export", type="TRIANGULATE")
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def shade_smooth_objects(objects):
    shaded = 0
    for obj in objects:
        if not obj.data.polygons:
            continue
        for poly in obj.data.polygons:
            poly.use_smooth = True
        obj.data.update()
        shaded += 1
    return shaded


def mesh_summary(objects):
    return {
        "objects": len(objects),
        "vertices": sum(len(obj.data.vertices) for obj in objects),
        "faces": sum(len(obj.data.polygons) for obj in objects),
        "boundary_edges": sum(boundary_edge_count(obj.data) for obj in objects),
    }


def export_mesh(path: Path, objects=None):
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_OUTPUTS:
        raise RuntimeError(f"Unsupported output mesh format: {path.suffix}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if objects is None:
        objects = mesh_objects()
    if not objects:
        raise RuntimeError("No mesh objects to export.")

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if suffix == ".stl":
        if hasattr(bpy.ops.wm, "stl_export"):
            try:
                bpy.ops.wm.stl_export(
                    filepath=str(path),
                    export_selected_objects=True,
                    ascii_format=False,
                    forward_axis=FORWARD_AXIS,
                    up_axis=UP_AXIS,
                )
                return
            except TypeError:
                bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True)
                return

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
        return

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
