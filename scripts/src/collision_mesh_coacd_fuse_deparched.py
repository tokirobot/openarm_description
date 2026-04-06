import argparse
import json
import shutil
from pathlib import Path
from typing import Optional

import numpy as np


SUPPORTED_EXTENSIONS = (".stl", ".obj", ".ply")


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


def parse_optional_float(value):
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"none", "off", "false"}:
        return None
    return float(value)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Fuse an existing CoACD joined STL without voxel remeshing. "
            "Default mode splits mesh islands and runs a Manifold boolean union."
        )
    )
    parser.add_argument("input", type=Path,
                        help="Input CoACD STL/mesh file or directory.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for fused outputs. Default: input_dir/fused.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process mesh files recursively when input is a directory.",
    )
    parser.add_argument(
        "--extensions",
        default="stl",
        help="Comma-separated extensions to process in directory mode. Default: stl.",
    )
    parser.add_argument(
        "--mode",
        choices=("manifold", "inflate-manifold", "bridge", "weld"),
        default="manifold",
        help=(
            "Fusion mode. manifold runs boolean union on mesh islands. weld only "
            "snaps nearby vertices and cleans faces; bridge removes one small "
            "triangle on each close component and connects the holes with a "
            "triangular tube. inflate-manifold slightly inflates each hull before "
            "Manifold union so near-contact hulls overlap. Default: manifold."
        ),
    )
    parser.add_argument(
        "--contact-tol",
        type=parse_optional_float,
        default=None,
        metavar="FLOAT|none",
        help=(
            "Optional component grouping tolerance. When set, only components "
            "with vertices within this distance are unioned together. Default: "
            "none, which unions all components in one call."
        ),
    )
    parser.add_argument(
        "--inflate-distance",
        type=float,
        default=2e-4,
        help=(
            "Outward vertex-normal offset for --mode inflate-manifold. Default: "
            "2e-4 mesh units."
        ),
    )
    parser.add_argument(
        "--shrink-after-inflate",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "After inflate-manifold union, move output vertices inward by the "
            "same distance along vertex normals. Default: true."
        ),
    )
    parser.add_argument(
        "--bridge-tol",
        type=float,
        default=1e-5,
        help=(
            "Maximum component distance for --mode bridge. Components are joined "
            "with a minimal spanning set of close pairs. Default: 1e-5."
        ),
    )
    parser.add_argument(
        "--weld-tol",
        type=float,
        default=1e-6,
        help="Vertex snap tolerance for --mode weld. Default: 1e-6.",
    )
    parser.add_argument(
        "--duplicate-faces",
        choices=("keep-first", "remove-all", "keep-all"),
        default="keep-first",
        help=(
            "How --mode weld handles duplicate faces after snapping. keep-first "
            "keeps one copy; remove-all removes every repeated face group; "
            "keep-all leaves them untouched. Default: keep-first."
        ),
    )
    parser.add_argument(
        "--check-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Pass check_volume to trimesh.boolean.union in manifold mode. "
            "Default: false."
        ),
    )
    parser.add_argument(
        "--fix-component-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Fix component normals before Manifold union. Default: true.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep intermediate grouped component STLs under _work/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned work without writing files.",
    )
    return parser.parse_args()


def parse_extensions(raw: str):
    extensions = []
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = "." + item
        if item not in SUPPORTED_EXTENSIONS:
            raise SystemExit(f"Unsupported extension: {item}")
        extensions.append(item)

    if not extensions:
        raise SystemExit("At least one extension is required.")

    return tuple(dict.fromkeys(extensions))


def is_under(path: Path, root: Optional[Path]):
    if root is None:
        return False
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def iter_mesh_files(input_path: Path, recursive: bool, extensions, excluded_roots):
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise SystemExit(f"Unsupported input mesh format: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise SystemExit(f"Input path does not exist: {input_path}")

    pattern = "**/*" if recursive else "*"
    files = []
    for path in input_path.glob(pattern):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        if any(is_under(path, root) for root in excluded_roots):
            continue
        files.append(path)

    return sorted(files)


def resolve_output_path(input_mesh: Path, input_root: Path, output_root: Path):
    if input_root.is_dir():
        rel_parent = input_mesh.parent.relative_to(input_root)
        return output_root / rel_parent / input_mesh.name

    return output_root / input_mesh.name


def require_modules(args):
    missing = []
    try:
        import trimesh  # noqa: F401
    except ModuleNotFoundError:
        missing.append("trimesh")

    if args.mode in {"manifold", "inflate-manifold"}:
        try:
            import manifold3d  # noqa: F401
        except ModuleNotFoundError:
            missing.append("manifold3d")

    if args.contact_tol is not None or args.mode in {"bridge", "weld"}:
        try:
            import scipy  # noqa: F401
        except ModuleNotFoundError:
            missing.append("scipy")

    if missing:
        raise SystemExit(
            "Missing Python dependency: "
            + ", ".join(missing)
            + "\nInstall them in the local venv with: .venv/bin/python -m pip install "
            + " ".join(missing)
        )


def load_mesh(path: Path):
    import trimesh

    mesh = trimesh.load(path, force="mesh", process=True)
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    return mesh


def clean_component(mesh, fix_normals: bool):
    if fix_normals:
        mesh.fix_normals()
        if mesh.is_watertight and mesh.volume < 0:
            mesh.invert()
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    return mesh


def component_distance_groups(components, contact_tol):
    if contact_tol is None:
        return [list(range(len(components)))]

    from scipy.spatial import cKDTree

    parent = list(range(len(components)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    trees = [cKDTree(component.vertices) for component in components]
    for i, component in enumerate(components):
        for j in range(i + 1, len(components)):
            pairs = trees[j].query_ball_point(
                component.vertices, r=contact_tol)
            if any(pairs):
                union(i, j)

    groups = {}
    for index in range(len(components)):
        groups.setdefault(find(index), []).append(index)

    return list(groups.values())


def manifold_fuse(components, groups, output_stl: Path, check_volume: bool, work_dir: Path, keep_work: bool):
    import trimesh

    fused_groups = []
    for group_index, group in enumerate(groups):
        group_meshes = [components[index] for index in group]
        if len(group_meshes) == 1:
            fused = group_meshes[0].copy()
        else:
            fused = trimesh.boolean.union(
                group_meshes,
                engine="manifold",
                check_volume=check_volume,
            )
            if fused is None:
                raise RuntimeError(
                    f"Manifold union returned None for group {group}.")

        fused.merge_vertices()
        fused.remove_unreferenced_vertices()
        fused_groups.append(fused)

        if keep_work:
            work_dir.mkdir(parents=True, exist_ok=True)
            fused.export(work_dir / f"group_{group_index:03d}.stl")

    output = trimesh.util.concatenate(fused_groups)
    output.merge_vertices()
    output.remove_unreferenced_vertices()
    output_stl.parent.mkdir(parents=True, exist_ok=True)
    output.export(output_stl)
    return output


def offset_component_vertices(component, distance):
    import trimesh

    mesh = component.copy()
    mesh.fix_normals()
    normals = np.array(mesh.vertex_normals, dtype=np.float64, copy=True)
    lengths = np.linalg.norm(normals, axis=1)
    good = lengths > 1e-12
    normals[good] /= lengths[good, None]

    if not np.all(good):
        radial = np.array(mesh.vertices - mesh.centroid,
                          dtype=np.float64, copy=True)
        radial_lengths = np.linalg.norm(radial, axis=1)
        radial_good = radial_lengths > 1e-12
        radial[radial_good] /= radial_lengths[radial_good, None]
        normals[~good] = radial[~good]

    return trimesh.Trimesh(
        vertices=mesh.vertices + distance * normals,
        faces=mesh.faces,
        process=True,
    )


def inflate_manifold_fuse(
    components,
    output_stl: Path,
    inflate_distance: float,
    shrink_after_inflate: bool,
    check_volume: bool,
    work_dir: Path,
    keep_work: bool,
):
    import trimesh

    inflated = [
        offset_component_vertices(component, inflate_distance)
        for component in components
    ]
    output = trimesh.boolean.union(
        inflated,
        engine="manifold",
        check_volume=check_volume,
    )
    if output is None:
        raise RuntimeError(
            "Manifold union returned None for inflated components.")

    output.merge_vertices()
    output.remove_unreferenced_vertices()
    output.fix_normals()

    if shrink_after_inflate:
        output = offset_component_vertices(output, -inflate_distance)
        output.merge_vertices()
        output.remove_unreferenced_vertices()
        output.fix_normals()

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    output.export(output_stl)

    if keep_work:
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, component in enumerate(inflated):
            component.export(work_dir / f"inflated_component_{index:03d}.stl")

    details = {
        "inflate_distance": inflate_distance,
        "shrink_after_inflate": shrink_after_inflate,
        "check_volume": check_volume,
    }
    return output, details


def closest_component_edges(components, max_distance):
    from scipy.spatial import cKDTree

    candidates = []
    trees = [cKDTree(component.vertices) for component in components]
    for i, component in enumerate(components):
        for j in range(i + 1, len(components)):
            distances, indices = trees[j].query(component.vertices, k=1)
            best_local = int(np.argmin(distances))
            best_distance = float(distances[best_local])
            if best_distance <= max_distance:
                candidates.append(
                    {
                        "distance": best_distance,
                        "a": i,
                        "b": j,
                        "vertex_a": best_local,
                        "vertex_b": int(indices[best_local]),
                    }
                )

    candidates.sort(key=lambda item: item["distance"])
    parent = list(range(len(components)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    selected = []
    for candidate in candidates:
        root_a = find(candidate["a"])
        root_b = find(candidate["b"])
        if root_a == root_b:
            continue
        parent[root_b] = root_a
        selected.append(candidate)

    return selected, candidates


def nearest_face_to_vertex(component, vertex_index, used_faces):
    face_indices = np.where(np.any(component.faces == vertex_index, axis=1))[0]
    if len(face_indices) == 0:
        face_indices = np.arange(len(component.faces))

    vertex = component.vertices[vertex_index]
    best_face = None
    best_distance = None
    for face_index in face_indices:
        if face_index in used_faces:
            continue
        centroid = component.triangles_center[face_index]
        distance = float(np.linalg.norm(centroid - vertex))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_face = int(face_index)

    if best_face is None:
        raise RuntimeError(
            "Could not find an unused bridge face on a component.")

    return best_face


def aligned_loop(loop_a, loop_b):
    best_loop = None
    best_score = None
    variants = []
    for reverse in (False, True):
        base = loop_b[::-1] if reverse else loop_b
        for shift in range(3):
            variants.append(np.roll(base, -shift, axis=0))

    for candidate in variants:
        score = float(np.linalg.norm(loop_a - candidate, axis=1).sum())
        if best_score is None or score < best_score:
            best_score = score
            best_loop = candidate

    return best_loop


def bridge_fuse(components, bridge_tol: float, output_stl: Path, work_dir: Path, keep_work: bool):
    import trimesh

    selected_edges, candidate_edges = closest_component_edges(
        components, bridge_tol)
    if not selected_edges:
        output = trimesh.util.concatenate(components)
        output.merge_vertices()
        output.remove_unreferenced_vertices()
        output_stl.parent.mkdir(parents=True, exist_ok=True)
        output.export(output_stl)
        return output, {
            "bridge_tol": bridge_tol,
            "candidate_edge_count": len(candidate_edges),
            "selected_edge_count": 0,
            "selected_edges": [],
        }

    component_offsets = []
    vertices = []
    faces = []
    face_component_offsets = []
    vertex_offset = 0
    face_offset = 0
    for component in components:
        component_offsets.append(vertex_offset)
        vertices.append(component.vertices)
        faces.append(component.faces + vertex_offset)
        face_component_offsets.append(face_offset)
        vertex_offset += len(component.vertices)
        face_offset += len(component.faces)

    vertices = np.vstack(vertices)
    faces = np.vstack(faces)
    remove_faces = set()
    used_component_faces = {index: set() for index in range(len(components))}
    bridge_faces = []
    bridge_records = []

    for edge in selected_edges:
        comp_a = components[edge["a"]]
        comp_b = components[edge["b"]]
        face_a = nearest_face_to_vertex(
            comp_a,
            edge["vertex_a"],
            used_component_faces[edge["a"]],
        )
        face_b = nearest_face_to_vertex(
            comp_b,
            edge["vertex_b"],
            used_component_faces[edge["b"]],
        )
        used_component_faces[edge["a"]].add(face_a)
        used_component_faces[edge["b"]].add(face_b)

        global_face_a = face_component_offsets[edge["a"]] + face_a
        global_face_b = face_component_offsets[edge["b"]] + face_b
        remove_faces.add(global_face_a)
        remove_faces.add(global_face_b)

        loop_a = faces[global_face_a]
        loop_b_original = faces[global_face_b]
        loop_b_points = aligned_loop(
            vertices[loop_a], vertices[loop_b_original])
        # Convert aligned points back to indices by matching rows from the original loop.
        aligned_indices = []
        remaining = list(loop_b_original)
        for point in loop_b_points:
            best_pos = min(
                range(len(remaining)),
                key=lambda idx: float(np.linalg.norm(
                    vertices[remaining[idx]] - point)),
            )
            aligned_indices.append(remaining.pop(best_pos))
        loop_b = np.asarray(aligned_indices, dtype=np.int64)

        for index in range(3):
            next_index = (index + 1) % 3
            a0 = int(loop_a[index])
            a1 = int(loop_a[next_index])
            b0 = int(loop_b[index])
            b1 = int(loop_b[next_index])
            bridge_faces.append([a0, a1, b1])
            bridge_faces.append([a0, b1, b0])

        bridge_records.append(
            {
                "a": edge["a"],
                "b": edge["b"],
                "distance": edge["distance"],
                "face_a": face_a,
                "face_b": face_b,
            }
        )

    keep_mask = np.ones(len(faces), dtype=bool)
    if remove_faces:
        keep_mask[list(remove_faces)] = False
    kept_faces = faces[keep_mask]
    if bridge_faces:
        kept_faces = np.vstack(
            [kept_faces, np.asarray(bridge_faces, dtype=np.int64)])

    output = trimesh.Trimesh(vertices=vertices, faces=kept_faces, process=True)
    output.merge_vertices()
    output.remove_unreferenced_vertices()
    output.fix_normals()
    output_stl.parent.mkdir(parents=True, exist_ok=True)
    output.export(output_stl)

    if keep_work:
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, component in enumerate(components):
            component.export(work_dir / f"component_{index:03d}.stl")

    details = {
        "bridge_tol": bridge_tol,
        "candidate_edge_count": len(candidate_edges),
        "selected_edge_count": len(selected_edges),
        "selected_edges": bridge_records,
    }
    return output, details


def weld_vertices(mesh, tolerance: float, duplicate_faces: str):
    import trimesh
    from scipy.spatial import cKDTree

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)

    tree = cKDTree(vertices)
    pairs = list(tree.query_pairs(tolerance))

    parent = np.arange(len(vertices))
    rank = np.zeros(len(vertices), dtype=np.int8)

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        root_a = find(a)
        root_b = find(b)
        if root_a == root_b:
            return
        if rank[root_a] < rank[root_b]:
            root_a, root_b = root_b, root_a
        parent[root_b] = root_a
        if rank[root_a] == rank[root_b]:
            rank[root_a] += 1

    for a, b in pairs:
        union(a, b)

    roots = np.array([find(index) for index in range(len(vertices))])
    _, inverse = np.unique(roots, return_inverse=True)
    welded_vertices = np.zeros((inverse.max() + 1, 3), dtype=np.float64)
    counts = np.bincount(inverse)
    np.add.at(welded_vertices, inverse, vertices)
    welded_vertices /= counts[:, None]

    welded_faces = inverse[faces]
    nondegenerate = np.logical_and.reduce(
        (
            welded_faces[:, 0] != welded_faces[:, 1],
            welded_faces[:, 1] != welded_faces[:, 2],
            welded_faces[:, 0] != welded_faces[:, 2],
        )
    )
    welded_faces = welded_faces[nondegenerate]

    if duplicate_faces != "keep-all" and len(welded_faces):
        sorted_faces = np.sort(welded_faces, axis=1)
        _, face_inverse, face_counts = np.unique(
            sorted_faces,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        if duplicate_faces == "remove-all":
            welded_faces = welded_faces[face_counts[face_inverse] == 1]
        elif duplicate_faces == "keep-first":
            keep = np.zeros(len(welded_faces), dtype=bool)
            seen = set()
            for index, face_key in enumerate(face_inverse):
                if face_key not in seen:
                    keep[index] = True
                    seen.add(face_key)
            welded_faces = welded_faces[keep]

    output = trimesh.Trimesh(vertices=welded_vertices,
                             faces=welded_faces, process=True)
    output.merge_vertices()
    output.remove_unreferenced_vertices()
    return output, len(pairs)


def mesh_stats(mesh):
    components = mesh.split(only_watertight=False)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "is_watertight": bool(mesh.is_watertight),
        "component_count": int(len(components)),
        "volume": float(mesh.volume) if mesh.is_watertight else None,
    }


def process_one(args, input_mesh: Path, input_root: Path, output_root: Path, work_root: Path):
    output_stl = resolve_output_path(input_mesh, input_root, output_root)
    manifest_path = output_stl.with_suffix(".fuse.json")
    rel_stem = output_stl.relative_to(output_root).with_suffix("")
    work_dir = work_root / rel_stem

    print(f"\n[INFO] Processing: {input_mesh}")
    print(f"[INFO] Output STL: {output_stl}")
    print(f"[INFO] Mode: {args.mode}")
    if args.contact_tol is not None:
        print(f"[INFO] Contact tolerance: {args.contact_tol}")

    if args.dry_run:
        return

    source = load_mesh(input_mesh)
    components = [
        clean_component(component.copy(), args.fix_component_normals)
        for component in source.split(only_watertight=False)
    ]

    if args.mode == "manifold":
        groups = component_distance_groups(components, args.contact_tol)
        output = manifold_fuse(
            components,
            groups,
            output_stl,
            check_volume=args.check_volume,
            work_dir=work_dir,
            keep_work=args.keep_work,
        )
        mode_details = {
            "check_volume": args.check_volume,
            "fix_component_normals": args.fix_component_normals,
            "contact_tol": args.contact_tol,
            "group_count": len(groups),
            "groups": groups,
        }
    elif args.mode == "inflate-manifold":
        output, mode_details = inflate_manifold_fuse(
            components,
            output_stl,
            inflate_distance=args.inflate_distance,
            shrink_after_inflate=args.shrink_after_inflate,
            check_volume=args.check_volume,
            work_dir=work_dir,
            keep_work=args.keep_work,
        )
    elif args.mode == "bridge":
        output, mode_details = bridge_fuse(
            components,
            args.bridge_tol,
            output_stl,
            work_dir=work_dir,
            keep_work=args.keep_work,
        )
    elif args.mode == "weld":
        output, pair_count = weld_vertices(
            source, args.weld_tol, args.duplicate_faces)
        output_stl.parent.mkdir(parents=True, exist_ok=True)
        output.export(output_stl)
        mode_details = {
            "weld_tol": args.weld_tol,
            "duplicate_faces": args.duplicate_faces,
            "near_pair_count": pair_count,
        }
    else:
        raise RuntimeError(f"Unknown mode: {args.mode}")

    exported = load_mesh(output_stl)
    manifest = {
        "input": str(input_mesh),
        "output_stl": str(output_stl),
        "mode": args.mode,
        "mode_details": mode_details,
        "source_stats": mesh_stats(source),
        "component_stats": [mesh_stats(component) for component in components],
        "pre_export_output_stats": mesh_stats(output),
        "exported_output_stats": mesh_stats(exported),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if work_dir.exists() and not args.keep_work:
        shutil.rmtree(work_dir)

    print(f"[INFO] Source components: {len(components)}")
    print(f"[INFO] Exported output stats: {manifest['exported_output_stats']}")
    print(f"[INFO] Manifest: {manifest_path}")


def main():
    args = parse_args()
    input_path = args.input.resolve()
    extensions = parse_extensions(args.extensions)
    input_base = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_base / "fused"
    )
    work_root = output_root / "_work"
    excluded_roots = (output_root, input_base / "_parts", input_base / "_work")

    if not args.dry_run:
        require_modules(args)

    mesh_files = iter_mesh_files(
        input_path=input_path,
        recursive=args.recursive,
        extensions=extensions,
        excluded_roots=excluded_roots,
    )
    if not mesh_files:
        print(f"[WARN] No mesh files found under {input_path}")
        return

    print(f"[INFO] Input: {input_path}")
    print(f"[INFO] Output root: {output_root}")
    print(f"[INFO] Mesh count: {len(mesh_files)}")
    print(f"[INFO] Mode: {args.mode}")

    failures = []
    for mesh_path in mesh_files:
        try:
            process_one(
                args=args,
                input_mesh=mesh_path.resolve(),
                input_root=input_path,
                output_root=output_root,
                work_root=work_root,
            )
        except Exception as exc:
            failures.append((mesh_path, exc))
            print(f"[ERROR] Failed processing {mesh_path}: {exc}")

    if failures:
        print("\n[ERROR] Batch completed with failures:")
        for path, exc in failures:
            print(f"  - {path}: {exc}")
        raise SystemExit(1)

    print("\n[INFO] Batch completed successfully.")


if __name__ == "__main__":
    main()
