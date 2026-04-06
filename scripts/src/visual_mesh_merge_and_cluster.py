import bpy
import sys
import math
import bmesh
import re
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from mathutils import Matrix, Vector, kdtree


# ============================================================
# Scene utilities
# ============================================================

def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_dae(path: Path):
    if not hasattr(bpy.ops.wm, "collada_import"):
        raise RuntimeError(
            "This Blender build does not provide bpy.ops.wm.collada_import. "
            "Use Blender 4.2 LTS / 3.6 LTS / another build with COLLADA support."
        )

    bpy.ops.wm.collada_import(filepath=str(path), import_units=True)


def read_collada_up_axis(path: Path):
    collada_ns = "http://www.collada.org/2005/11/COLLADASchema"

    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        print(f"[WARN] Failed to read COLLADA up_axis from {path}: {e}")
        return None

    up_axis = root.find(f".//{{{collada_ns}}}up_axis")
    if up_axis is None or not up_axis.text:
        return None

    return up_axis.text.strip()


def convert_all_convertible_objects_to_mesh():
    """
    Convert curve/surface/font objects to mesh.
    Keep EMPTY objects because they may preserve DAE hierarchy.
    """
    for obj in list(bpy.context.scene.objects):
        obj.select_set(False)

    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CURVE", "SURFACE", "FONT"}:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            try:
                bpy.ops.object.convert(target="MESH")
            except Exception as e:
                print(f"[WARN] Failed to convert {obj.name}: {e}")


# ============================================================
# Hierarchy utilities
# ============================================================

def get_depth_from_root(obj):
    """
    Root object depth = 0.
    Direct child of root depth = 1.
    Grandchild depth = 2.
    """
    depth = 0
    cur = obj

    while cur.parent is not None:
        depth += 1
        cur = cur.parent

    return depth


def print_tree(obj, level=0):
    indent = "  " * level
    depth = get_depth_from_root(obj)
    print(
        f"{indent}- {obj.name} | type={obj.type} | "
        f"depth={depth} | children={len(obj.children)}"
    )

    for child in obj.children:
        print_tree(child, level + 1)


def print_scene_tree():
    roots = [obj for obj in bpy.context.scene.objects if obj.parent is None]
    print("[INFO] Scene tree:")

    for root in roots:
        print_tree(root)


def has_mesh_descendant(obj):
    for child in obj.children:
        if child.type == "MESH":
            return True
        if has_mesh_descendant(child):
            return True

    return False


def collect_leaf_meshes():
    """
    Leaf mesh = MESH object with no mesh descendants.
    """
    leaf_meshes = []

    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and not has_mesh_descendant(obj):
            leaf_meshes.append(obj)

    return leaf_meshes


def get_ancestor_chain(obj):
    chain = []
    cur = obj

    while cur is not None:
        chain.append(cur)
        cur = cur.parent

    return chain


def get_parent_key(obj, depth_from_leaf=1):
    """
    depth_from_leaf=1:
      direct parent

    depth_from_leaf=2:
      grandparent
    """
    chain = get_ancestor_chain(obj)

    if len(chain) > depth_from_leaf:
        return chain[depth_from_leaf].name

    return "__root__"


def group_leaf_meshes_by_parent(leaf_meshes, depth_from_leaf=1):
    groups = defaultdict(list)

    for obj in leaf_meshes:
        key = get_parent_key(obj, depth_from_leaf=depth_from_leaf)
        groups[key].append(obj)

    return groups


# ============================================================
# Boundary / openness utilities
# ============================================================

def get_boundary_edge_indices(obj):
    """
    Return boundary edge vertex-index pairs.
    Boundary edge = edge used by exactly one polygon.
    """
    if obj.type != "MESH":
        return []

    mesh = obj.data
    edge_face_count = {}

    for poly in mesh.polygons:
        verts = list(poly.vertices)
        n = len(verts)

        for i in range(n):
            a = verts[i]
            b = verts[(i + 1) % n]
            key = tuple(sorted((a, b)))
            edge_face_count[key] = edge_face_count.get(key, 0) + 1

    boundary_edges = []

    for edge_key, count in edge_face_count.items():
        if count == 1:
            boundary_edges.append(edge_key)

    return boundary_edges


def get_boundary_vertices_world(obj):
    """
    Return boundary vertices in world coordinates.
    """
    if obj.type != "MESH":
        return []

    mesh = obj.data
    out = []

    for a, b in get_boundary_edge_indices(obj):
        out.append(obj.matrix_world @ mesh.vertices[a].co)
        out.append(obj.matrix_world @ mesh.vertices[b].co)

    return out


def get_boundary_vertices_world_for_contact(
    obj,
    merge_distance=0.0,
    degenerate_threshold=1e-12,
):
    """
    Return boundary vertices for contact detection.

    merge_distance is applied only to a temporary bmesh copy. This lets contact
    grouping see through tiny duplicate-vertex cracks without modifying the
    original mesh that will later be exported.
    """
    if obj.type != "MESH":
        return []

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if merge_distance and merge_distance > 0:
        bmesh.ops.remove_doubles(
            bm,
            verts=list(bm.verts),
            dist=merge_distance,
        )

        try:
            bmesh.ops.dissolve_degenerate(
                bm,
                edges=list(bm.edges),
                dist=degenerate_threshold,
            )
        except Exception as e:
            print(
                f"[WARN] contact bmesh dissolve_degenerate failed on {obj.name}: {e}")

    out = []

    for edge in bm.edges:
        if edge.is_boundary:
            out.append(obj.matrix_world @ edge.verts[0].co)
            out.append(obj.matrix_world @ edge.verts[1].co)

    bm.free()
    return out


def deduplicate_points_by_distance(points, distance):
    if not points or distance <= 0:
        return list(points)

    unique = []
    kd = kdtree.KDTree(len(points))

    for point in points:
        if unique and kd.find_range(point, distance):
            continue

        kd.insert(point, len(unique))
        unique.append(point)
        kd.balance()

    return unique


def is_open_mesh(obj):
    return len(get_boundary_edge_indices(obj)) > 0


def boundary_vertices_have_contact(
    verts_a,
    verts_b,
    tol=1e-5,
    min_matches=20,
    min_match_ratio=0.01,
):
    if not verts_a or not verts_b:
        return False

    kd = kdtree.KDTree(len(verts_b))

    for i, p in enumerate(verts_b):
        kd.insert(p, i)

    kd.balance()

    match_count = 0

    for p in verts_a:
        found = kd.find_range(p, tol)
        if found:
            match_count += 1

    required_by_ratio = int(min(len(verts_a), len(verts_b)) * min_match_ratio)
    required = max(min_matches, required_by_ratio)

    return match_count >= required


# ============================================================
# Union find
# ============================================================

class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]

        return x

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)

        if ra != rb:
            self.parent[rb] = ra

    def groups(self):
        out = {}

        for x in self.parent:
            r = self.find(x)
            out.setdefault(r, []).append(x)

        return list(out.values())


def cluster_open_objects_by_line_contact(
    objects,
    tol=1e-5,
    min_matches=20,
    min_match_ratio=0.01,
    boundary_dedupe_distance=1e-6,
    contact_merge_distance=0.0,
):
    """
    Cluster only open objects by boundary line/ring contact.
    Closed objects should not be passed here.
    """
    if len(objects) <= 1:
        return [objects]

    boundary_cache = {}

    for obj in objects:
        if contact_merge_distance and contact_merge_distance > 0:
            boundary_points = get_boundary_vertices_world_for_contact(
                obj,
                merge_distance=contact_merge_distance,
            )
        else:
            boundary_points = get_boundary_vertices_world(obj)

        boundary_cache[obj] = deduplicate_points_by_distance(
            boundary_points,
            distance=boundary_dedupe_distance,
        )

    uf = UnionFind(objects)
    n = len(objects)

    for i in range(n):
        for j in range(i + 1, n):
            a = objects[i]
            b = objects[j]

            if boundary_vertices_have_contact(
                boundary_cache[a],
                boundary_cache[b],
                tol=tol,
                min_matches=min_matches,
                min_match_ratio=min_match_ratio,
            ):
                print(f"[INFO] Contact detected: {a.name} <-> {b.name}")
                uf.union(a, b)

    return uf.groups()


# ============================================================
# Conservative cleanup
# ============================================================

def clean_single_part_object(obj, degenerate_threshold=1e-12):
    """
    Conservative cleanup for visual mesh.

    Applied to each original leaf mesh separately.

    This does not merge vertices. Vertex merging for contact detection is done
    on temporary bmesh copies so the exported mesh is not modified globally.
    """
    if obj.type != "MESH":
        return

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")

    try:
        bpy.ops.mesh.dissolve_degenerate(threshold=degenerate_threshold)
    except Exception as e:
        print(f"[WARN] dissolve_degenerate failed on {obj.name}: {e}")

    bpy.ops.object.mode_set(mode="OBJECT")

    if is_open_mesh(obj):
        print(
            f"[INFO] Skip global normal recalculation on open mesh: {obj.name}")
        return

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")

    try:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    except Exception as e:
        print(f"[WARN] normals_make_consistent failed on {obj.name}: {e}")

    bpy.ops.object.mode_set(mode="OBJECT")


# ============================================================
# Material / color utilities
# ============================================================

def get_material_rgba(mat):
    if mat is None:
        return (0.5, 0.5, 0.5, 1.0)

    if mat.use_nodes and mat.node_tree is not None:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
                c = node.inputs["Base Color"].default_value
                return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))

    c = mat.diffuse_color
    return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))


def get_object_representative_rgba(obj):
    """
    Object-level representative color.

    This does NOT split faces.
    It only checks which material slot dominates this object by face area,
    then assigns the whole object to that representative color.
    """
    if obj.type != "MESH":
        return (0.5, 0.5, 0.5, 1.0)

    mesh = obj.data

    if not mesh.materials:
        return (0.5, 0.5, 0.5, 1.0)

    material_area = {}

    for poly in mesh.polygons:
        idx = poly.material_index
        material_area[idx] = material_area.get(idx, 0.0) + float(poly.area)

    if material_area:
        dominant_index = max(material_area, key=material_area.get)
    else:
        dominant_index = 0

    if dominant_index >= len(mesh.materials):
        dominant_index = 0

    mat = mesh.materials[dominant_index]
    return get_material_rgba(mat)


def triangle_area(a, b, c):
    return 0.5 * (b - a).cross(c - a).length


def get_object_world_surface_area(obj):
    if obj.type != "MESH":
        return 0.0

    mesh = obj.data
    world = obj.matrix_world
    area = 0.0

    for poly in mesh.polygons:
        vertices = [world @ mesh.vertices[i].co for i in poly.vertices]

        if len(vertices) < 3:
            continue

        origin = vertices[0]

        for i in range(1, len(vertices) - 1):
            area += triangle_area(origin, vertices[i], vertices[i + 1])

    return area


def get_object_world_bbox_metrics(obj):
    if obj.type != "MESH":
        return {
            "center": (0.0, 0.0, 0.0),
            "dimensions": (0.0, 0.0, 0.0),
            "diagonal": 0.0,
        }

    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]

    mins = tuple(min(p[i] for p in points) for i in range(3))
    maxs = tuple(max(p[i] for p in points) for i in range(3))
    dimensions = tuple(maxs[i] - mins[i] for i in range(3))
    center = tuple((mins[i] + maxs[i]) * 0.5 for i in range(3))
    diagonal = math.sqrt(sum(dim * dim for dim in dimensions))

    return {
        "center": center,
        "dimensions": dimensions,
        "diagonal": diagonal,
    }


def color_distance_rgb(c1, c2):
    return math.sqrt(
        (c1[0] - c2[0]) ** 2 +
        (c1[1] - c2[1]) ** 2 +
        (c1[2] - c2[2]) ** 2
    )


def cluster_objects_by_color(objects, threshold=0.08):
    """
    Cluster whole objects by representative color.
    No face-level split is performed.

    The cluster output color is the representative color with the largest
    accumulated mesh area inside that cluster. This preserves dominant dark
    parts instead of washing them toward gray with an arithmetic RGB average.
    """
    clusters = []

    for obj in objects:
        rgba = get_object_representative_rgba(obj)
        area = get_object_world_surface_area(obj)

        assigned = False

        for cluster in clusters:
            if color_distance_rgb(rgba, cluster["color"]) <= threshold:
                cluster["objects"].append(obj)
                cluster["color_area"][rgba] = (
                    cluster["color_area"].get(rgba, 0.0) + area
                )

                cluster["color"] = max(
                    cluster["color_area"],
                    key=cluster["color_area"].get,
                )

                assigned = True
                break

        if not assigned:
            clusters.append(
                {
                    "color": rgba,
                    "color_area": {rgba: area},
                    "objects": [obj],
                }
            )

    return clusters


def make_principled_material(name, rgba):
    mat = bpy.data.materials.new(name=name)
    mat.diffuse_color = rgba
    mat.use_nodes = True

    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            if "Base Color" in node.inputs:
                node.inputs["Base Color"].default_value = rgba
            if "Alpha" in node.inputs:
                node.inputs["Alpha"].default_value = rgba[3]

    return mat


# ============================================================
# Object duplication / joining
# ============================================================

def duplicate_object_world_space(obj):
    """
    Duplicate an object and bake its world transform into mesh vertices.
    """
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    new_obj.animation_data_clear()

    bpy.context.collection.objects.link(new_obj)

    world_matrix = obj.matrix_world.copy()
    new_obj.data.transform(world_matrix)
    new_obj.matrix_world = Matrix.Identity(4)

    return new_obj


def join_objects_as_cluster(objects, cluster_name, unify_material_rgba=None):
    """
    Join whole objects into one mesh object.
    Does not split faces.

    If unify_material_rgba is provided, the joined mesh will be assigned
    one unified material.
    """
    if not objects:
        raise RuntimeError(f"Empty cluster: {cluster_name}")

    duplicates = []

    for obj in objects:
        dup = duplicate_object_world_space(obj)
        duplicates.append(dup)

    bpy.ops.object.select_all(action="DESELECT")

    for obj in duplicates:
        obj.select_set(True)

    bpy.context.view_layer.objects.active = duplicates[0]

    if len(duplicates) > 1:
        bpy.ops.object.join()

    joined = bpy.context.view_layer.objects.active
    joined.name = cluster_name
    joined.data.name = cluster_name

    if unify_material_rgba is not None:
        mat = make_principled_material(
            f"{cluster_name}_mat", unify_material_rgba)

        joined.data.materials.clear()
        joined.data.materials.append(mat)

        for poly in joined.data.polygons:
            poly.material_index = 0

    return joined


def remove_objects(objects):
    for obj in list(objects):
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def weld_boundary_vertices_by_distance(obj, distance, degenerate_threshold=1e-12):
    """
    Weld boundary vertices on a joined repair unit.

    This is intentionally used only after multiple open leaf meshes have been
    accepted as a contact cluster. The contact test is conservative; the weld
    distance should stay at the same scale as contact_tol. Limiting the weld to
    boundary vertices avoids merging nearby interior detail by accident.
    """
    if obj.type != "MESH" or distance <= 0:
        return 0

    mesh = obj.data
    before = len(mesh.vertices)

    bm = bmesh.new()
    bm.from_mesh(mesh)

    boundary_verts = {
        vert
        for edge in bm.edges
        if edge.is_boundary
        for vert in edge.verts
    }

    if not boundary_verts:
        bm.free()
        print(
            f"[INFO] No boundary vertices available for welding in {obj.name}")
        return 0

    bmesh.ops.remove_doubles(
        bm,
        verts=list(boundary_verts),
        dist=distance,
    )

    try:
        bmesh.ops.dissolve_degenerate(
            bm,
            edges=list(bm.edges),
            dist=degenerate_threshold,
        )
    except Exception as e:
        print(
            f"[WARN] dissolve_degenerate after weld failed on {obj.name}: {e}")

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    after = len(mesh.vertices)
    welded = before - after

    if welded:
        print(
            f"[INFO] Welded {welded} vertices in {obj.name} "
            f"with boundary distance={distance}"
        )
    else:
        print(
            f"[INFO] No vertices welded in {obj.name} "
            f"with boundary distance={distance}"
        )

    return welded


def cleanup_final_export_mesh_object(obj, degenerate_threshold=1e-12):
    """
    Conservative final cleanup before exporting OBJ/DAE.

    Loose edges may be exported as COLLADA <lines>, which some lightweight DAE
    viewers do not handle. Loose vertices are also not useful for visual meshes.
    """
    if obj.type != "MESH":
        return

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    loose_edges = [edge for edge in bm.edges if not edge.link_faces]

    if loose_edges:
        print(
            f"[INFO] Removing {len(loose_edges)} loose edges from {obj.name}")
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")

    loose_verts = [
        vert
        for vert in bm.verts
        if not vert.link_edges and not vert.link_faces
    ]

    if loose_verts:
        print(
            f"[INFO] Removing {len(loose_verts)} loose vertices from {obj.name}")
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")

    try:
        bmesh.ops.dissolve_degenerate(
            bm,
            edges=list(bm.edges),
            dist=degenerate_threshold,
        )
    except Exception as e:
        print(f"[WARN] final dissolve_degenerate failed on {obj.name}: {e}")

    bm.to_mesh(mesh)
    mesh.update()
    bm.free()


# ============================================================
# Repair stage
# ============================================================

def make_repair_units(
    leaf_meshes,
    prefix,
    parent_depth=1,
    contact_tol=1e-5,
    min_matches=20,
    min_match_ratio=0.01,
    boundary_dedupe_distance=1e-6,
    contact_merge_distance=0.0,
    min_repair_depth=2,
    weld_distance=None,
):
    """
    Stage 1:
      - group leaf meshes by parent/subassembly
      - shallow leaf meshes are not aggregated
      - closed meshes are not aggregated
      - only open depth-eligible meshes are clustered by line contact
      - each output repair unit is one Blender object
    """
    parent_groups = group_leaf_meshes_by_parent(
        leaf_meshes,
        depth_from_leaf=parent_depth,
    )

    repair_units = []
    repair_records = []
    repair_index = 0

    if weld_distance is None:
        weld_distance = contact_tol

    print(f"[INFO] Parent group count: {len(parent_groups)}")

    for parent_key, objects in parent_groups.items():
        print(f"[INFO] Parent group: {parent_key}, objects={len(objects)}")

        shallow_objects = []
        depth_eligible_objects = []

        for obj in objects:
            depth = get_depth_from_root(obj)

            if depth < min_repair_depth:
                shallow_objects.append(obj)
            else:
                depth_eligible_objects.append(obj)

        # Shallow objects: keep as individual repair units.
        for obj in shallow_objects:
            name = f"{prefix}_repair_{repair_index:03d}"
            repair_index += 1

            print(
                f"[INFO] Repair skip shallow: {obj.name}, "
                f"depth={get_depth_from_root(obj)}"
            )

            unit = join_objects_as_cluster([obj], name)
            repair_units.append(unit)

            repair_records.append(
                {
                    "repair_unit": name,
                    "reason": "skip_shallow_leaf_mesh",
                    "parent_key": parent_key,
                    "objects": [obj.name],
                }
            )

        closed_objects = []
        open_objects = []

        for obj in depth_eligible_objects:
            if is_open_mesh(obj):
                open_objects.append(obj)
            else:
                closed_objects.append(obj)

        # Closed objects: keep as individual repair units.
        for obj in closed_objects:
            name = f"{prefix}_repair_{repair_index:03d}"
            repair_index += 1

            print(
                f"[INFO] Repair skip closed: {obj.name}, "
                f"depth={get_depth_from_root(obj)}"
            )

            unit = join_objects_as_cluster([obj], name)
            repair_units.append(unit)

            repair_records.append(
                {
                    "repair_unit": name,
                    "reason": "skip_closed_mesh",
                    "parent_key": parent_key,
                    "objects": [obj.name],
                }
            )

        print(
            f"[INFO] Open and depth-eligible objects under {parent_key}: "
            f"{len(open_objects)}"
        )

        if open_objects:
            contact_clusters = cluster_open_objects_by_line_contact(
                open_objects,
                tol=contact_tol,
                min_matches=min_matches,
                min_match_ratio=min_match_ratio,
                boundary_dedupe_distance=boundary_dedupe_distance,
                contact_merge_distance=contact_merge_distance,
            )
        else:
            contact_clusters = []

        for cluster_objs in contact_clusters:
            name = f"{prefix}_repair_{repair_index:03d}"
            repair_index += 1

            reason = (
                "aggregate_open_line_contact"
                if len(cluster_objs) > 1
                else "single_open_no_contact"
            )

            print(
                f"[INFO] Repair unit {name}: "
                f"reason={reason}, objects={len(cluster_objs)}"
            )

            unit = join_objects_as_cluster(cluster_objs, name)

            welded_vertices = 0
            if len(cluster_objs) > 1:
                welded_vertices = weld_boundary_vertices_by_distance(
                    unit,
                    distance=weld_distance,
                )

            repair_units.append(unit)

            repair_records.append(
                {
                    "repair_unit": name,
                    "reason": reason,
                    "parent_key": parent_key,
                    "weld_distance": weld_distance if len(cluster_objs) > 1 else 0.0,
                    "welded_vertices": welded_vertices,
                    "objects": [o.name for o in cluster_objs],
                }
            )

    return repair_units, repair_records


# ============================================================
# Export
# ============================================================

def export_obj(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if hasattr(bpy.ops.wm, "obj_export"):
        try:
            bpy.ops.wm.obj_export(
                filepath=str(path),
                export_selected_objects=True,
                export_materials=True,
                export_uv=True,
                export_normals=True,
                export_triangulated_mesh=True,
                forward_axis="NEGATIVE_Z",
                up_axis="Y",
            )
        except TypeError:
            bpy.ops.wm.obj_export(
                filepath=str(path),
                export_selected_objects=True,
                export_materials=True,
                export_uv=True,
                export_normals=True,
                forward_axis="NEGATIVE_Z",
                up_axis="Y",
            )
    else:
        bpy.ops.export_scene.obj(
            filepath=str(path),
            use_selection=True,
            use_materials=True,
            use_uvs=True,
            use_normals=True,
            axis_forward="-Z",
            axis_up="Y",
        )


def export_stl(objects, path: Path):
    if not hasattr(bpy.ops.wm, "stl_export") and not hasattr(bpy.ops.export_mesh, "stl"):
        print("[WARN] STL export operator not found. Skipping STL export.")
        return

    if not objects:
        print("[WARN] No objects to export as STL.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if hasattr(bpy.ops.wm, "stl_export"):
        try:
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True,
                forward_axis="NEGATIVE_Z",
                up_axis="Y",
            )
        except TypeError:
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True,
            )
    else:
        bpy.ops.export_mesh.stl(
            filepath=str(path),
            use_selection=True,
            axis_forward="-Z",
            axis_up="Y",
        )


def safe_file_stem(name):
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return stem or "object"


def short_part_name_from_prefix(prefix):
    if prefix.endswith("_obj"):
        return prefix[:-4]

    return prefix


def parse_comma_separated_names(value):
    if not value:
        return []

    names = []
    for item in value.split(","):
        name = item.strip()
        if name:
            names.append(name)

    return names


def build_repair_unit_analysis_records(
    repair_units,
    delete_max_diag=0.025,
    delete_max_area=0.0015,
    delete_max_dim=0.02,
    delete_max_faces=3000,
    manual_delete_units=None,
):
    manual_delete_units = set(manual_delete_units or [])
    metrics = []

    for obj in repair_units:
        bbox = get_object_world_bbox_metrics(obj)
        metrics.append(
            {
                "object": obj,
                "name": obj.name,
                "surface_area": get_object_world_surface_area(obj),
                "bbox_center": bbox["center"],
                "bbox_dimensions": bbox["dimensions"],
                "bbox_diagonal": bbox["diagonal"],
                "rgba": get_object_representative_rgba(obj),
                "vertex_count": len(obj.data.vertices) if obj.type == "MESH" else 0,
                "face_count": len(obj.data.polygons) if obj.type == "MESH" else 0,
            }
        )

    for item in metrics:
        max_dim = max(item["bbox_dimensions"])
        small_by_area = item["surface_area"] <= delete_max_area
        small_by_diag = item["bbox_diagonal"] <= delete_max_diag
        small_by_dim = max_dim <= delete_max_dim
        simple_enough = item["face_count"] <= delete_max_faces

        if item["name"] in manual_delete_units:
            item["analysis_action"] = "manual_delete"
        elif small_by_area and small_by_diag and small_by_dim and simple_enough:
            item["analysis_action"] = "delete_candidate"
        else:
            item["analysis_action"] = "keep_candidate"

        item["bbox_max_dim"] = max_dim
        item["delete_max_diag"] = delete_max_diag
        item["delete_max_area"] = delete_max_area
        item["delete_max_dim"] = delete_max_dim
        item["delete_max_faces"] = delete_max_faces

    return metrics


def split_repair_units_by_delete_records(repair_units, records):
    delete_objects = {
        item["object"]
        for item in records
        if item["analysis_action"] in {"delete_candidate", "manual_delete"}
    }

    kept = [obj for obj in repair_units if obj not in delete_objects]
    deleted = [obj for obj in repair_units if obj in delete_objects]

    return kept, deleted


def evaluate_delete_policy(
    repair_units,
    delete_max_diag=0.025,
    delete_max_area=0.0015,
    delete_max_dim=0.02,
    delete_max_faces=3000,
    manual_delete_units=None,
):
    records = build_repair_unit_analysis_records(
        repair_units,
        delete_max_diag=delete_max_diag,
        delete_max_area=delete_max_area,
        delete_max_dim=delete_max_dim,
        delete_max_faces=delete_max_faces,
        manual_delete_units=manual_delete_units,
    )
    kept, deleted = split_repair_units_by_delete_records(repair_units, records)

    return kept, deleted, records


def export_repair_unit_analysis(
    records,
    analysis_dir: Path,
):
    """
    Export every repaired unit for review before the destructive delete path.

    This is intentionally an analysis-only side path. Files in delete/ are
    candidates suggested by size metrics; they are not removed from the normal
    color clustering/export pipeline.
    """
    keep_dir = analysis_dir / "keep"
    delete_dir = analysis_dir / "delete"
    keep_dir.mkdir(parents=True, exist_ok=True)
    delete_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] Writing repair-unit analysis OBJ files: "
        f"{analysis_dir}"
    )

    for item in records:
        target_dir = (
            delete_dir
            if item["analysis_action"] in {"delete_candidate", "manual_delete"}
            else keep_dir
        )
        export_obj(item["object"], target_dir /
                   f"{safe_file_stem(item['name'])}.obj")

    report_path = analysis_dir / "analysis_report.tsv"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(
            "action\tname\tsurface_area\tbbox_diagonal\t"
            "bbox_max_dim\tbbox_dx\tbbox_dy\tbbox_dz\tcenter_x\tcenter_y\tcenter_z\t"
            "rgba_r\trgba_g\trgba_b\trgba_a\tvertices\tfaces\t"
            "delete_max_diag\tdelete_max_area\tdelete_max_dim\tdelete_max_faces\n"
        )

        for item in records:
            dims = item["bbox_dimensions"]
            center = item["bbox_center"]
            rgba = item["rgba"]
            f.write(
                f"{item['analysis_action']}\t"
                f"{item['name']}\t"
                f"{item['surface_area']:.12g}\t"
                f"{item['bbox_diagonal']:.12g}\t"
                f"{item['bbox_max_dim']:.12g}\t"
                f"{dims[0]:.12g}\t{dims[1]:.12g}\t{dims[2]:.12g}\t"
                f"{center[0]:.12g}\t{center[1]:.12g}\t{center[2]:.12g}\t"
                f"{rgba[0]:.6f}\t{rgba[1]:.6f}\t{rgba[2]:.6f}\t{rgba[3]:.6f}\t"
                f"{item['vertex_count']}\t{item['face_count']}\t"
                f"{item['delete_max_diag']:.12g}\t"
                f"{item['delete_max_area']:.12g}\t"
                f"{item['delete_max_dim']:.12g}\t"
                f"{item['delete_max_faces']}\n"
            )

    delete_list_path = analysis_dir / "delete_candidates.txt"
    with open(delete_list_path, "w", encoding="utf-8") as f:
        f.write(
            "# Delete candidates generated by the current absolute-size policy "
            "and manual delete list.\n"
            "# Columns: name surface_area bbox_diagonal bbox_max_dim "
            "bbox_dx bbox_dy bbox_dz vertices faces action rgba\n"
        )
        for item in records:
            if item["analysis_action"] in {"delete_candidate", "manual_delete"}:
                dims = item["bbox_dimensions"]
                rgba = item["rgba"]
                f.write(
                    f"{item['name']}\t"
                    f"{item['surface_area']:.12g}\t"
                    f"{item['bbox_diagonal']:.12g}\t"
                    f"{item['bbox_max_dim']:.12g}\t"
                    f"{dims[0]:.12g}\t{dims[1]:.12g}\t{dims[2]:.12g}\t"
                    f"{item['vertex_count']}\t{item['face_count']}\t"
                    f"{item['analysis_action']}\t"
                    f"{rgba[0]:.6f} {rgba[1]:.6f} {rgba[2]:.6f} {rgba[3]:.6f}\n"
                )

    delete_count = sum(
        1
        for item in records
        if item["analysis_action"] in {"delete_candidate", "manual_delete"}
    )
    print(
        f"[INFO] Analysis export complete: keep={len(records) - delete_count}, "
        f"delete_candidates={delete_count}, report={report_path}"
    )

    return records


def export_grouped_dae(objects, path: Path, source_up_axis=None):
    if not hasattr(bpy.ops.wm, "collada_export"):
        print("[WARN] collada_export not found. Skipping grouped DAE export.")
        return

    if not objects:
        print("[WARN] No objects to export as DAE.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")

    for obj in objects:
        obj.select_set(True)

    bpy.context.view_layer.objects.active = objects[0]

    try:
        bpy.ops.wm.collada_export(
            filepath=str(path),
            selected=True,
            include_children=False,
            apply_modifiers=True,
            triangulate=True,
            use_object_instantiation=False,
        )
    except TypeError:
        bpy.ops.wm.collada_export(
            filepath=str(path),
            selected=True,
        )

    strip_collada_line_primitives(path)

    if source_up_axis == "Y_UP":
        convert_collada_zup_export_to_yup(path)


def strip_collada_line_primitives(path: Path):
    """
    Remove COLLADA <lines> primitives from exported DAE files.

    This is a compatibility pass for viewers that expect mesh-only DAE content.
    It keeps triangles, materials, and the visual scene intact.
    """
    collada_ns = "http://www.collada.org/2005/11/COLLADASchema"
    ET.register_namespace("", collada_ns)

    tree = ET.parse(path)
    root = tree.getroot()
    removed = 0

    for mesh in root.findall(f".//{{{collada_ns}}}mesh"):
        for child in list(mesh):
            if child.tag == f"{{{collada_ns}}}lines":
                mesh.remove(child)
                removed += 1

    if removed:
        print(
            f"[INFO] Removed {removed} COLLADA <lines> primitives from {path}")
        tree.write(path, encoding="utf-8", xml_declaration=True)


def convert_collada_zup_export_to_yup(path: Path):
    """
    Convert Blender's Z_UP COLLADA export back to the source Y_UP convention.

    Blender imports the original Y_UP DAE into its internal Z_UP scene and then
    exports a Z_UP DAE. Some downstream consumers in this repository expect the
    original Y_UP coordinate convention and effectively ignore the COLLADA
    up_axis metadata. For those files, rotate position and normal arrays back
    with (x, y, z) -> (x, z, -y), then restore <up_axis>Y_UP</up_axis>.
    This is a proper rotation, so triangle winding is left unchanged.
    """
    collada_ns = "http://www.collada.org/2005/11/COLLADASchema"
    ET.register_namespace("", collada_ns)

    tree = ET.parse(path)
    root = tree.getroot()

    up_axis = root.find(f".//{{{collada_ns}}}up_axis")
    if up_axis is None:
        return

    if (up_axis.text or "").strip() != "Z_UP":
        return

    converted_arrays = 0

    for source in root.findall(f".//{{{collada_ns}}}source"):
        source_id = source.attrib.get("id", "").lower()

        if (
            "position" not in source_id
            and "verts" not in source_id
            and "normal" not in source_id
        ):
            continue

        float_array = source.find(f"{{{collada_ns}}}float_array")
        if float_array is None or not float_array.text:
            continue

        values = [float(x) for x in float_array.text.split()]

        if len(values) % 3 != 0:
            continue

        for i in range(0, len(values), 3):
            y = values[i + 1]
            z = values[i + 2]
            values[i + 1] = z
            values[i + 2] = -y

        float_array.text = " ".join(f"{value:.9g}" for value in values)
        converted_arrays += 1

    up_axis.text = "Y_UP"

    if converted_arrays:
        print(
            f"[INFO] Converted {converted_arrays} COLLADA position/normal arrays "
            f"from Blender Z_UP export back to Y_UP: {path}"
        )
        tree.write(path, encoding="utf-8", xml_declaration=True)


def write_mujoco_preview_scene(path: Path, model_name, color_export_info):
    """
    Write a complete MJCF file for direct loading in viewers.

    The snippet writer above intentionally emits only <asset> and <geom>
    fragments. That is convenient for pasting into an existing robot XML but is
    not a valid standalone XML document because it has multiple root elements.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<mujoco model="{model_name}">\n')
        f.write("  <asset>\n")

        for item in color_export_info:
            f.write(
                f'    <mesh name="{item["mesh_name"]}" file="{item["obj_file"]}"/>\n'
            )

        for item in color_export_info:
            rgba = item["rgba"]
            f.write(
                f'    <material name="{item["mesh_name"]}_mat" '
                f'rgba="{rgba[0]:.6f} {rgba[1]:.6f} {rgba[2]:.6f} {rgba[3]:.6f}"/>\n'
            )

        f.write("  </asset>\n")
        f.write("  <worldbody>\n")
        f.write(f'    <body name="{model_name}">\n')

        for item in color_export_info:
            f.write(
                f'      <geom type="mesh" mesh="{item["mesh_name"]}" '
                f'material="{item["mesh_name"]}_mat" '
                f'contype="0" conaffinity="0" group="1"/>\n'
            )

        f.write("    </body>\n")
        f.write("  </worldbody>\n")
        f.write("</mujoco>\n")


def write_report(path: Path, repair_records, color_records):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Repair records\n\n")

        for rec in repair_records:
            f.write(f"repair_unit: {rec['repair_unit']}\n")
            f.write(f"reason: {rec['reason']}\n")
            f.write(f"parent_key: {rec['parent_key']}\n")
            if "welded_vertices" in rec:
                f.write(f"weld_distance: {rec['weld_distance']:.12g}\n")
                f.write(f"welded_vertices: {rec['welded_vertices']}\n")
            f.write(f"source_objects: {len(rec['objects'])}\n")

            for name in rec["objects"]:
                f.write(f"  - {name}\n")

            f.write("\n")

        f.write("\n# Color cluster records\n\n")

        for rec in color_records:
            rgba = rec["rgba"]
            f.write(f"color_unit: {rec['color_unit']}\n")
            f.write(
                f"rgba: {rgba[0]:.6f} {rgba[1]:.6f} {rgba[2]:.6f} {rgba[3]:.6f}\n")
            f.write(f"repair_units: {len(rec['repair_units'])}\n")

            for name in rec["repair_units"]:
                f.write(f"  - {name}\n")

            f.write("\n")


# ============================================================
# Main
# ============================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Repair open-face DAE mesh parts, optionally mark/delete small "
            "components, then cluster the result by dominant material color."
        )
    )
    parser.add_argument("input_dae", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("prefix")
    parser.add_argument("--parent-depth", type=int, default=1)
    parser.add_argument("--contact-tol", type=float, default=1e-5)
    parser.add_argument("--min-matches", type=int, default=20)
    parser.add_argument("--min-match-ratio", type=float, default=0.01)
    parser.add_argument("--boundary-dedupe-distance", type=float, default=1e-6)
    parser.add_argument("--merge-distance", type=float, default=0.0)
    parser.add_argument("--min-repair-depth", type=int, default=2)
    parser.add_argument("--color-threshold", type=float, default=0.08)
    parser.add_argument(
        "--no-import-cleanup",
        dest="import_cleanup",
        action="store_false",
        help=(
            "Skip conservative cleanup after import. By default the script "
            "dissolves degenerate geometry and recalculates normals for closed meshes."
        ),
    )
    parser.set_defaults(import_cleanup=True)
    parser.add_argument(
        "--no-export-cleanup",
        dest="export_cleanup",
        action="store_false",
        help=(
            "Skip conservative cleanup before final OBJ/DAE export. By default "
            "the script removes loose edges/vertices and dissolves degenerate geometry."
        ),
    )
    parser.set_defaults(export_cleanup=True)
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Write review outputs into output_dir/review/: keep/, delete/, "
            "analysis_report.tsv, and delete_candidates.txt."
        ),
    )
    parser.add_argument(
        "--export-stl",
        action="store_true",
        help=(
            "Also export repaired STL files next to the filtered/grouped DAE "
            "outputs."
        ),
    )
    parser.add_argument("--delete-max-diag", type=float, default=0.03)
    parser.add_argument("--delete-max-area", type=float, default=0.002)
    parser.add_argument("--delete-max-dim", type=float, default=0.025)
    parser.add_argument("--delete-max-faces", type=int, default=5000)
    parser.add_argument(
        "--manual-delete-units",
        default="",
        help=(
            "Comma-separated repair unit names to force-delete, for example "
            "link3_obj_repair_004,link3_obj_repair_006."
        ),
    )

    return parser.parse_args(argv)


def main():
    if "--" not in sys.argv:
        raise SystemExit(
            "Usage:\n"
            "  blender --background --python merge_and_cluster.py -- "
            "input.dae output_dir prefix [options]\n\n"
            "Run with --help after Blender's -- separator for all options."
        )

    args = parse_args(sys.argv[sys.argv.index("--") + 1:])

    input_dae = args.input_dae.resolve()
    output_dir = args.output_dir.resolve()
    prefix = args.prefix
    manual_delete_units = parse_comma_separated_names(args.manual_delete_units)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Input DAE: {input_dae}")
    print(f"[INFO] Output dir: {output_dir}")
    print(f"[INFO] Prefix: {prefix}")
    print(f"[INFO] Parent depth for repair candidates: {args.parent_depth}")
    print(f"[INFO] Contact tolerance: {args.contact_tol}")
    print(f"[INFO] Min matches: {args.min_matches}")
    print(f"[INFO] Min match ratio: {args.min_match_ratio}")
    print(f"[INFO] Boundary dedupe distance: {args.boundary_dedupe_distance}")
    print(f"[INFO] Contact-detection merge distance: {args.merge_distance}")
    print(
        f"[INFO] Weld distance for accepted open-contact clusters: {args.contact_tol}")
    print(f"[INFO] Min repair depth: {args.min_repair_depth}")
    print(f"[INFO] Color threshold: {args.color_threshold}")
    print(f"[INFO] Import cleanup: {args.import_cleanup}")
    print(f"[INFO] Export cleanup: {args.export_cleanup}")
    print(f"[INFO] Dev review outputs: {args.dev}")
    print(f"[INFO] Export STL: {args.export_stl}")
    print("[INFO] Apply delete filter: True")
    print(f"[INFO] Delete candidate max bbox diagonal: {args.delete_max_diag}")
    print(f"[INFO] Delete candidate max surface area: {args.delete_max_area}")
    print(f"[INFO] Delete candidate max bbox dimension: {args.delete_max_dim}")
    print(f"[INFO] Delete candidate max faces: {args.delete_max_faces}")
    print(f"[INFO] Manual delete units: {manual_delete_units or []}")

    clear_scene()

    source_up_axis = read_collada_up_axis(input_dae)
    print(f"[INFO] Source COLLADA up_axis: {source_up_axis or 'unknown'}")

    print("[INFO] Importing DAE...")
    import_dae(input_dae)

    print("[INFO] Converting convertible objects to mesh...")
    convert_all_convertible_objects_to_mesh()

    print_scene_tree()

    leaf_meshes = collect_leaf_meshes()
    print(f"[INFO] Leaf mesh count: {len(leaf_meshes)}")

    if not leaf_meshes:
        raise RuntimeError("No leaf mesh objects found.")

    if args.import_cleanup:
        print("[INFO] Conservative cleanup for each original leaf mesh...")
        for obj in leaf_meshes:
            clean_single_part_object(
                obj,
                degenerate_threshold=1e-12,
            )
    else:
        print("[INFO] Skipping import cleanup for original leaf meshes.")

    print("[INFO] Stage 1: structure-assisted repair grouping...")
    repair_units, repair_records = make_repair_units(
        leaf_meshes=leaf_meshes,
        prefix=prefix,
        parent_depth=args.parent_depth,
        contact_tol=args.contact_tol,
        min_matches=args.min_matches,
        min_match_ratio=args.min_match_ratio,
        boundary_dedupe_distance=args.boundary_dedupe_distance,
        contact_merge_distance=args.merge_distance,
        min_repair_depth=args.min_repair_depth,
    )

    print(f"[INFO] Repair unit count: {len(repair_units)}")

    delete_kept_units, delete_removed_units, delete_records = evaluate_delete_policy(
        repair_units=repair_units,
        delete_max_diag=args.delete_max_diag,
        delete_max_area=args.delete_max_area,
        delete_max_dim=args.delete_max_dim,
        delete_max_faces=args.delete_max_faces,
        manual_delete_units=manual_delete_units,
    )

    if args.dev:
        print("[INFO] Stage 1 analysis side export...")
        export_repair_unit_analysis(
            records=delete_records,
            analysis_dir=output_dir / "review",
        )

    print("[INFO] Applying formal delete filter before color clustering...")
    print(
        f"[INFO] Formal delete filter: kept={len(delete_kept_units)}, "
        f"deleted={len(delete_removed_units)}"
    )

    for obj in delete_removed_units:
        print(f"[INFO] Formal delete candidate removed: {obj.name}")

    remove_objects(delete_removed_units)
    repair_units = delete_kept_units

    if not repair_units:
        raise RuntimeError(
            "All repair units were removed by the formal delete filter.")

    print("[INFO] Removing original leaf meshes...")
    remove_objects(leaf_meshes)

    part_name = short_part_name_from_prefix(prefix)
    filtered_dae_path = output_dir / f"{part_name}_filtered.dae"
    print(
        f"[INFO] Exporting filtered DAE before color grouping: {filtered_dae_path}")
    export_grouped_dae(repair_units, filtered_dae_path,
                       source_up_axis=source_up_axis)
    if args.export_stl:
        filtered_stl_path = output_dir / f"{part_name}_filtered.stl"
        print(
            f"[INFO] Exporting filtered STL before color grouping: {filtered_stl_path}")
        export_stl(repair_units, filtered_stl_path)

    print("[INFO] Stage 2: color clustering after repair...")
    color_clusters = cluster_objects_by_color(
        repair_units,
        threshold=args.color_threshold,
    )

    print(f"[INFO] Color cluster count: {len(color_clusters)}")

    final_color_objects = []
    color_export_info = []
    color_records = []

    if args.export_cleanup:
        print("[INFO] Final export cleanup is enabled before OBJ/DAE export.")
    else:
        print("[INFO] Skipping final export cleanup before OBJ/DAE export.")

    for i, cluster in enumerate(color_clusters):
        rgba = cluster["color"]
        objects = cluster["objects"]

        color_name = f"{part_name}_{i:02d}"

        print(
            f"[INFO] Color cluster {i:02d}: "
            f"objects={len(objects)}, "
            f"rgba=({rgba[0]:.3f}, {rgba[1]:.3f}, {rgba[2]:.3f}, {rgba[3]:.3f})"
        )

        final_obj = join_objects_as_cluster(
            objects,
            color_name,
            unify_material_rgba=rgba,
        )

        if args.export_cleanup:
            cleanup_final_export_mesh_object(final_obj)

        final_color_objects.append(final_obj)

        obj_path = output_dir / f"{color_name}.obj"
        print(f"[INFO] Exporting final color OBJ: {obj_path}")
        export_obj(final_obj, obj_path)

        color_export_info.append(
            {
                "mesh_name": color_name,
                "obj_file": obj_path.name,
                "rgba": rgba,
            }
        )

        color_records.append(
            {
                "color_unit": color_name,
                "rgba": rgba,
                "repair_units": [o.name for o in objects],
            }
        )

    print("[INFO] Removing intermediate repair units...")
    remove_objects(repair_units)

    grouped_dae_path = output_dir / f"{part_name}_filtered_grouped.dae"
    print(f"[INFO] Exporting final grouped DAE: {grouped_dae_path}")
    export_grouped_dae(final_color_objects, grouped_dae_path,
                       source_up_axis=source_up_axis)
    if args.export_stl:
        grouped_stl_path = output_dir / f"{part_name}_filtered_grouped.stl"
        print(f"[INFO] Exporting final grouped STL: {grouped_stl_path}")
        export_stl(final_color_objects, grouped_stl_path)

    preview_scene_path = output_dir / f"{prefix}_mujoco_preview.xml"
    print(f"[INFO] Writing MuJoCo preview scene: {preview_scene_path}")
    write_mujoco_preview_scene(preview_scene_path, prefix, color_export_info)

    report_path = output_dir / f"{prefix}_repair_color_report.txt"
    print(f"[INFO] Writing report: {report_path}")
    write_report(report_path, repair_records, color_records)

    print("[INFO] Done.")
    print(f"[INFO] Filtered DAE: {filtered_dae_path}")
    print(f"[INFO] Final grouped DAE: {grouped_dae_path}")
    if args.export_stl:
        print(f"[INFO] Filtered STL: {filtered_stl_path}")
        print(f"[INFO] Final grouped STL: {grouped_stl_path}")
    print(f"[INFO] MuJoCo preview scene: {preview_scene_path}")
    print(f"[INFO] Report: {report_path}")


if __name__ == "__main__":
    main()
