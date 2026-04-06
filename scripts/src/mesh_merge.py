import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


SUPPORTED_EXTENSIONS = {".stl", ".obj", ".ply"}


def parse_bool(value):
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise argparse.ArgumentTypeError(f"Expected true/false, got {value!r}.")


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
            "Merge STL/OBJ/PLY meshes into one STL/OBJ by simple joining, "
            "Manifold boolean union, inflate-Manifold union, weld-only merging, "
            "Blender voxel remesh, or split connected components into files."
        )
    )
    parser.add_argument("input_meshes", type=Path, nargs="+")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output STL or OBJ path for a single merge job. For --mode split, "
            "this is the component output directory. Required when multiple "
            "input files should become one output file."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Output folder for per-input processing. Use this for directory "
            "input or when processing one joined STL into a sibling result."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process mesh files recursively when an input is a directory.",
    )
    parser.add_argument(
        "--extensions",
        default="stl",
        help="Comma-separated extensions to process in directory mode. Default: stl.",
    )
    parser.add_argument(
        "--mode",
        choices=("joined", "manifold", "inflate-manifold", "weld", "blender", "split"),
        default="joined",
        help="Merge method. Default: joined.",
    )
    parser.add_argument(
        "--component-format",
        choices=("stl", "obj"),
        default="stl",
        help="Output format for --mode split component files. Default: stl.",
    )
    parser.add_argument(
        "--split-components",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Split loaded meshes into connected components before merging. "
            "Useful for a single joined STL. Default: true."
        ),
    )
    parser.add_argument(
        "--process",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Let trimesh process loaded meshes. Default: true.",
    )
    parser.add_argument(
        "--check-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Pass check_volume to trimesh.boolean.union. Default: false.",
    )
    parser.add_argument(
        "--contact-tol",
        type=parse_optional_float,
        default=None,
        metavar="FLOAT|none",
        help=(
            "For --mode manifold, union only connected groups whose components "
            "have vertices within this distance. Default: none, which unions "
            "all components in one call."
        ),
    )
    parser.add_argument(
        "--fix-component-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Fix component normals before Manifold operations, inverting "
            "negative-volume watertight components. Default: true."
        ),
    )
    parser.add_argument(
        "--inflate-distance",
        type=float,
        default=2e-4,
        help=(
            "Outward vertex-normal offset for --mode inflate-manifold. "
            "Default: 2e-4 mesh units."
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
            "After inflate-Manifold union, move output vertices inward by the "
            "same distance along vertex normals. Default: true."
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
        "--keep-work",
        action="store_true",
        help="Keep temporary/intermediate component files where the selected mode writes them.",
    )
    parser.add_argument(
        "--manifest",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Write output sidecar JSON with mesh statistics. Default: true.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned merge jobs without loading meshes or writing files.",
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Blender executable for --mode blender.",
    )
    parser.add_argument(
        "--blender-script",
        type=Path,
        default=Path(__file__).with_name("blender_coacd_union_remesh.py"),
        help="Blender join/boolean/voxel-remesh script.",
    )
    parser.add_argument(
        "--boolean-union",
        action="store_true",
        help="Ask Blender to Boolean-union separate input objects before remesh.",
    )
    parser.add_argument(
        "--boolean-solver",
        choices=("EXACT", "FAST"),
        default="EXACT",
        help="Blender Boolean solver for --boolean-union. Default: EXACT.",
    )
    parser.add_argument(
        "--voxel-remesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Apply Blender voxel remesh in --mode blender. Default: true.",
    )
    parser.add_argument(
        "--voxel-size",
        type=float,
        default=0.001,
        help="Blender voxel remesh size. Default: 0.001.",
    )
    parser.add_argument(
        "--adaptivity",
        type=float,
        default=0.0,
        help="Blender voxel remesh adaptivity. Default: 0.0.",
    )
    parser.add_argument(
        "--smooth-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="Shade Blender output smooth. Default: false.",
    )
    return parser.parse_args()


def parse_extensions(raw):
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


def is_under(path: Path, root: Path | None):
    if root is None:
        return False
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def collect_input_files(input_paths, recursive, extensions, output_root):
    files = []
    for input_path in input_paths:
        path = input_path.resolve()
        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise SystemExit(f"Unsupported input format: {path.suffix}")
            files.append(path)
            continue

        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(path.glob(pattern)):
                if not child.is_file():
                    continue
                if child.suffix.lower() not in extensions:
                    continue
                if is_under(child, output_root):
                    continue
                files.append(child.resolve())
            continue

        raise SystemExit(f"Input path does not exist: {path}")

    unique = []
    seen = set()
    for path in files:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def output_for_file(input_file: Path, input_paths, output_root: Path):
    directory_inputs = [path.resolve() for path in input_paths if path.resolve().is_dir()]
    for directory in directory_inputs:
        try:
            rel_path = input_file.relative_to(directory)
            return output_root / rel_path.with_suffix(input_file.suffix)
        except ValueError:
            pass
    return output_root / input_file.name


def component_output_dir_for_file(input_file: Path, input_paths, output_root: Path):
    return output_for_file(input_file, input_paths, output_root).with_suffix("")


def plan_jobs(args):
    output_root = args.output_root.resolve() if args.output_root is not None else None
    extensions = parse_extensions(args.extensions)
    inputs = collect_input_files(
        args.input_meshes,
        recursive=args.recursive,
        extensions=extensions,
        output_root=output_root,
    )
    if not inputs:
        raise SystemExit("No input mesh files found.")

    has_directory_input = any(path.resolve().is_dir() for path in args.input_meshes)
    if output_root is not None:
        if args.mode == "split":
            return [
                (
                    [input_file],
                    component_output_dir_for_file(
                        input_file,
                        args.input_meshes,
                        output_root,
                    ),
                )
                for input_file in inputs
            ]
        return [
            ([input_file], output_for_file(input_file, args.input_meshes, output_root))
            for input_file in inputs
        ]

    if args.output is None:
        raise SystemExit("--output is required unless --output-root is provided.")
    if has_directory_input:
        raise SystemExit("Directory input requires --output-root.")

    return [(inputs, args.output.resolve())]


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

    if args.split_components or args.mode == "split":
        try:
            import networkx  # noqa: F401
        except ModuleNotFoundError:
            missing.append("networkx")

    if args.contact_tol is not None or args.mode == "weld":
        try:
            import scipy  # noqa: F401
        except ModuleNotFoundError:
            missing.append("scipy")

    if missing:
        raise SystemExit(
            "Missing Python dependency: "
            + ", ".join(missing)
            + "\nInstall them with: .venv/bin/python -m pip install "
            + " ".join(missing)
        )


def validate_output_path(output_mesh):
    if output_mesh.suffix.lower() not in {".stl", ".obj"}:
        raise SystemExit(f"Unsupported output format: {output_mesh.suffix}")


def validate_output_directory(output_dir):
    if output_dir.exists() and not output_dir.is_dir():
        raise SystemExit(f"Component output path is not a directory: {output_dir}")


def scene_to_meshes(loaded):
    import trimesh

    if isinstance(loaded, trimesh.Scene):
        return [mesh for mesh in loaded.dump() if isinstance(mesh, trimesh.Trimesh)]
    if isinstance(loaded, trimesh.Trimesh):
        return [loaded]
    raise TypeError(f"Unsupported trimesh load result: {type(loaded)!r}")


def load_input_meshes(paths, process, split_components):
    import trimesh

    meshes = []
    for path in paths:
        loaded = trimesh.load(path, force=None, process=process)
        for mesh in scene_to_meshes(loaded):
            if split_components:
                parts = mesh.split(only_watertight=False)
                meshes.extend(parts if len(parts) > 0 else [mesh])
            else:
                meshes.append(mesh)

    cleaned = []
    for mesh in meshes:
        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            continue
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
        cleaned.append(mesh)
    if not cleaned:
        raise RuntimeError("No non-empty mesh geometry was loaded.")
    return cleaned


def clean_component(mesh, fix_normals):
    if fix_normals:
        mesh.fix_normals()
        if mesh.is_watertight and mesh.volume < 0:
            mesh.invert()
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    return mesh


def filter_boolean_components(components, volume_epsilon=1e-15):
    filtered = []
    skipped = []
    for index, mesh in enumerate(components):
        reason = None
        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            reason = "empty"
        elif not mesh.is_watertight:
            reason = "not_watertight"
        elif abs(mesh.volume) <= volume_epsilon:
            reason = "near_zero_volume"

        if reason is None:
            filtered.append(mesh)
        else:
            skipped.append(
                {
                    "index": index,
                    "reason": reason,
                    "vertices": int(len(mesh.vertices)),
                    "faces": int(len(mesh.faces)),
                    "is_watertight": bool(mesh.is_watertight),
                    "volume": float(mesh.volume) if mesh.is_watertight else None,
                }
            )

    if not filtered:
        raise RuntimeError("No watertight non-zero-volume components for boolean merge.")
    return filtered, skipped


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
            pairs = trees[j].query_ball_point(component.vertices, r=contact_tol)
            if any(pairs):
                union(i, j)

    groups = {}
    for index in range(len(components)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def mesh_stats(mesh):
    components = mesh.split(only_watertight=False)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "is_watertight": bool(mesh.is_watertight),
        "component_count": int(len(components)),
        "volume": float(mesh.volume) if mesh.is_watertight else None,
    }


def detailed_mesh_stats(mesh):
    stats = mesh_stats(mesh)
    stats.update(
        {
            "euler_number": int(mesh.euler_number),
            "bounds": mesh.bounds.tolist() if len(mesh.vertices) else None,
        }
    )
    return stats


def export_split_components(input_meshes, output_dir, process, component_format):
    import trimesh

    output_dir.mkdir(parents=True, exist_ok=True)
    records = []

    for source_index, input_mesh in enumerate(input_meshes):
        loaded = trimesh.load(input_mesh, force=None, process=process)
        source_component_index = 0
        for mesh_index, mesh in enumerate(scene_to_meshes(loaded)):
            parts = mesh.split(only_watertight=False)
            components = parts if len(parts) > 0 else [mesh]
            for component in components:
                if len(component.vertices) == 0 or len(component.faces) == 0:
                    continue
                component.merge_vertices()
                component.remove_unreferenced_vertices()

                name_parts = [input_mesh.stem]
                if len(input_meshes) > 1:
                    name_parts.insert(0, f"input_{source_index:02d}")
                if mesh_index > 0:
                    name_parts.append(f"mesh_{mesh_index:02d}")
                name_parts.append(f"component_{source_component_index:02d}")
                output_path = output_dir / ("_".join(name_parts) + f".{component_format}")
                component.export(output_path)

                record = detailed_mesh_stats(component)
                record.update(
                    {
                        "source_mesh": str(input_mesh),
                        "source_index": source_index,
                        "mesh_index": mesh_index,
                        "component_index": source_component_index,
                        "output_mesh": str(output_path),
                    }
                )
                records.append(record)
                source_component_index += 1

    if not records:
        raise RuntimeError("No non-empty mesh components were exported.")
    return records


def export_joined(meshes, output_mesh):
    import trimesh

    output_mesh.parent.mkdir(parents=True, exist_ok=True)
    result = trimesh.util.concatenate(meshes)
    result.export(output_mesh)
    return result


def export_manifold(meshes, output_mesh, check_volume, contact_tol, work_dir, keep_work):
    import trimesh

    output_mesh.parent.mkdir(parents=True, exist_ok=True)
    groups = component_distance_groups(meshes, contact_tol)
    fused_groups = []

    for group_index, group in enumerate(groups):
        group_meshes = [meshes[index] for index in group]
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
                    f"trimesh.boolean.union returned None for group {group}."
                )

        fused.merge_vertices()
        fused.remove_unreferenced_vertices()
        fused_groups.append(fused)

        if keep_work:
            work_dir.mkdir(parents=True, exist_ok=True)
            fused.export(work_dir / f"group_{group_index:03d}.stl")

    result = trimesh.util.concatenate(fused_groups)
    result.merge_vertices()
    result.remove_unreferenced_vertices()
    result.export(output_mesh)
    return result, {
        "check_volume": check_volume,
        "contact_tol": contact_tol,
        "group_count": len(groups),
        "groups": groups,
    }


def offset_component_vertices(component, distance):
    import trimesh

    mesh = component.copy()
    mesh.fix_normals()
    normals = np.array(mesh.vertex_normals, dtype=np.float64, copy=True)
    lengths = np.linalg.norm(normals, axis=1)
    good = lengths > 1e-12
    normals[good] /= lengths[good, None]

    if not np.all(good):
        radial = np.array(mesh.vertices - mesh.centroid, dtype=np.float64, copy=True)
        radial_lengths = np.linalg.norm(radial, axis=1)
        radial_good = radial_lengths > 1e-12
        radial[radial_good] /= radial_lengths[radial_good, None]
        normals[~good] = radial[~good]

    return trimesh.Trimesh(
        vertices=mesh.vertices + distance * normals,
        faces=mesh.faces,
        process=True,
    )


def export_inflate_manifold(
    meshes,
    output_mesh,
    inflate_distance,
    shrink_after_inflate,
    check_volume,
    work_dir,
    keep_work,
):
    import trimesh

    output_mesh.parent.mkdir(parents=True, exist_ok=True)
    inflated = [
        offset_component_vertices(component, inflate_distance)
        for component in meshes
    ]

    if len(inflated) == 1:
        result = inflated[0].copy()
    else:
        result = trimesh.boolean.union(
            inflated,
            engine="manifold",
            check_volume=check_volume,
        )
        if result is None:
            raise RuntimeError("trimesh.boolean.union returned None for inflated meshes.")

    result.merge_vertices()
    result.remove_unreferenced_vertices()
    result.fix_normals()

    if shrink_after_inflate:
        result = offset_component_vertices(result, -inflate_distance)
        result.merge_vertices()
        result.remove_unreferenced_vertices()
        result.fix_normals()

    result.export(output_mesh)

    if keep_work:
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, component in enumerate(inflated):
            component.export(work_dir / f"inflated_component_{index:03d}.stl")

    return result, {
        "inflate_distance": inflate_distance,
        "shrink_after_inflate": shrink_after_inflate,
        "check_volume": check_volume,
    }


def weld_vertices(mesh, tolerance, duplicate_faces):
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

    result = trimesh.Trimesh(vertices=welded_vertices, faces=welded_faces, process=True)
    result.merge_vertices()
    result.remove_unreferenced_vertices()
    return result, len(pairs)


def export_weld(meshes, output_mesh, weld_tol, duplicate_faces):
    import trimesh

    output_mesh.parent.mkdir(parents=True, exist_ok=True)
    source = trimesh.util.concatenate(meshes)
    result, pair_count = weld_vertices(source, weld_tol, duplicate_faces)
    result.export(output_mesh)
    return result, {
        "weld_tol": weld_tol,
        "duplicate_faces": duplicate_faces,
        "near_pair_count": pair_count,
    }


def export_component_stls(meshes, work_dir):
    paths = []
    work_dir.mkdir(parents=True, exist_ok=True)
    for index, mesh in enumerate(meshes):
        path = work_dir / f"component_{index:04d}.stl"
        mesh.export(path)
        paths.append(path)
    return paths


def build_blender_command(args, input_paths, output_mesh):
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.blender_script.resolve()),
        "--",
        *[str(path) for path in input_paths],
        str(output_mesh),
        "--voxel-remesh",
        str(args.voxel_remesh).lower(),
        "--voxel-size",
        f"{args.voxel_size:.10g}",
        "--adaptivity",
        f"{args.adaptivity:.10g}",
        "--smooth-normals",
        str(args.smooth_normals).lower(),
    ]
    if args.boolean_union:
        command.extend(["--boolean-union", "--boolean-solver", args.boolean_solver])
    return command


def run_blender_merge(args, meshes, output_mesh):
    if not args.blender_script.resolve().is_file():
        raise SystemExit(f"Blender script does not exist: {args.blender_script}")

    if args.keep_work:
        work_dir = output_mesh.parent / f"{output_mesh.stem}_mesh_merge_work"
        component_paths = export_component_stls(meshes, work_dir)
        command = build_blender_command(args, component_paths, output_mesh)
        print("[INFO] Blender command: " + " ".join(command))
        subprocess.run(command, check=True)
        return work_dir

    with tempfile.TemporaryDirectory(prefix="mesh_merge_") as tmp:
        component_paths = export_component_stls(meshes, Path(tmp))
        command = build_blender_command(args, component_paths, output_mesh)
        print("[INFO] Blender command: " + " ".join(command))
        subprocess.run(command, check=True)
    return None


def write_manifest(path, data):
    manifest_path = path.with_suffix(f".mesh_merge{path.suffix}.json")
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest_path


def process_job(args, input_meshes, output_mesh):
    if args.mode == "split":
        output_dir = output_mesh
        validate_output_directory(output_dir)
        print(f"[INFO] Input files: {len(input_meshes)}")
        print("[INFO] Mode: split")
        print(f"[INFO] Component output directory: {output_dir}")

        records = export_split_components(
            input_meshes,
            output_dir,
            process=args.process,
            component_format=args.component_format,
        )

        manifest_path = None
        if args.manifest:
            manifest_path = output_dir / f"{output_dir.name}.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "input_meshes": [str(path) for path in input_meshes],
                        "output_directory": str(output_dir),
                        "mode": args.mode,
                        "process": args.process,
                        "component_format": args.component_format,
                        "component_count": len(records),
                        "components": records,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        print(f"[INFO] Exported components: {len(records)}")
        for record in records:
            print(
                "[INFO]   - "
                f"component={record['component_index']:02d}, "
                f"vertices={record['vertices']}, faces={record['faces']}, "
                f"watertight={record['is_watertight']}, "
                f"output={record['output_mesh']}"
            )
        if manifest_path is not None:
            print(f"[INFO] Manifest: {manifest_path}")
        return

    validate_output_path(output_mesh)
    meshes = load_input_meshes(
        input_meshes,
        process=args.process,
        split_components=args.split_components,
    )
    source_stats = [mesh_stats(mesh) for mesh in meshes]
    mode_details = None

    print(f"[INFO] Input files: {len(input_meshes)}")
    print(f"[INFO] Loaded mesh components: {len(meshes)}")
    print(f"[INFO] Mode: {args.mode}")
    print(f"[INFO] Output mesh: {output_mesh}")

    work_dir = None
    skipped_components = []
    if args.mode == "joined":
        output = export_joined(meshes, output_mesh)
        output_stats = mesh_stats(output)
    elif args.mode == "manifold":
        components = [
            clean_component(mesh.copy(), args.fix_component_normals)
            for mesh in meshes
        ]
        components, skipped_components = filter_boolean_components(components)
        work_dir = output_mesh.parent / f"{output_mesh.stem}_mesh_merge_work"
        output, mode_details = export_manifold(
            components,
            output_mesh,
            check_volume=args.check_volume,
            contact_tol=args.contact_tol,
            work_dir=work_dir,
            keep_work=args.keep_work,
        )
        mode_details["fix_component_normals"] = args.fix_component_normals
        output_stats = mesh_stats(output)
    elif args.mode == "inflate-manifold":
        components = [
            clean_component(mesh.copy(), args.fix_component_normals)
            for mesh in meshes
        ]
        components, skipped_components = filter_boolean_components(components)
        work_dir = output_mesh.parent / f"{output_mesh.stem}_mesh_merge_work"
        output, mode_details = export_inflate_manifold(
            components,
            output_mesh,
            inflate_distance=args.inflate_distance,
            shrink_after_inflate=args.shrink_after_inflate,
            check_volume=args.check_volume,
            work_dir=work_dir,
            keep_work=args.keep_work,
        )
        mode_details["fix_component_normals"] = args.fix_component_normals
        output_stats = mesh_stats(output)
    elif args.mode == "weld":
        output, mode_details = export_weld(
            meshes,
            output_mesh,
            weld_tol=args.weld_tol,
            duplicate_faces=args.duplicate_faces,
        )
        output_stats = mesh_stats(output)
    elif args.mode == "blender":
        work_dir = run_blender_merge(args, meshes, output_mesh)
        import trimesh

        output = trimesh.load(output_mesh, force="mesh", process=True)
        output_stats = mesh_stats(output)
    else:
        raise RuntimeError(f"Unsupported mode: {args.mode}")

    if output_stats["vertices"] == 0 or output_stats["faces"] == 0:
        raise RuntimeError("Mesh merge produced empty output geometry.")

    manifest_path = None
    if args.manifest:
        manifest_path = write_manifest(
            output_mesh,
            {
                "input_meshes": [str(path) for path in input_meshes],
                "output_mesh": str(output_mesh),
                "mode": args.mode,
                "split_components": args.split_components,
                "source_component_count": len(meshes),
                "source_component_stats": source_stats,
                "skipped_components": skipped_components,
                "output_stats": output_stats,
                "blender": None
                if args.mode != "blender"
                else {
                    "boolean_union": args.boolean_union,
                    "boolean_solver": args.boolean_solver,
                    "voxel_remesh": args.voxel_remesh,
                    "voxel_size": args.voxel_size,
                    "adaptivity": args.adaptivity,
                    "smooth_normals": args.smooth_normals,
                    "work_dir": str(work_dir) if work_dir is not None else None,
                },
                "manifold": None
                if args.mode != "manifold"
                else mode_details,
                "inflate_manifold": None
                if args.mode != "inflate-manifold"
                else mode_details,
                "weld": None if args.mode != "weld" else mode_details,
            },
        )

    print(f"[INFO] Output stats: {output_stats}")
    if skipped_components:
        print(f"[INFO] Skipped boolean-incompatible components: {len(skipped_components)}")
        for component in skipped_components:
            print(
                "[INFO]   - "
                f"index={component['index']}, reason={component['reason']}, "
                f"vertices={component['vertices']}, faces={component['faces']}"
            )
    if manifest_path is not None:
        print(f"[INFO] Manifest: {manifest_path}")


def main():
    args = parse_args()
    jobs = plan_jobs(args)

    if args.dry_run:
        print("[DRY-RUN] Planned mesh merge jobs:")
        for input_meshes, output_mesh in jobs:
            inputs = ", ".join(str(path) for path in input_meshes)
            print(f"[DRY-RUN] {inputs} -> {output_mesh} mode={args.mode}")
        return

    require_modules(args)

    failures = []
    for input_meshes, output_mesh in jobs:
        try:
            print("")
            process_job(args, input_meshes, output_mesh)
        except Exception as exc:
            failures.append((input_meshes, output_mesh, exc))
            print(f"[ERROR] Failed processing {output_mesh}: {exc}")

    if failures:
        print("\n[ERROR] Mesh merge completed with failures:")
        for input_meshes, output_mesh, exc in failures:
            inputs = ", ".join(str(path) for path in input_meshes)
            print(f"  - {inputs} -> {output_mesh}: {exc}")
        raise SystemExit(1)

    print("\n[INFO] Mesh merge completed successfully.")


if __name__ == "__main__":
    main()
