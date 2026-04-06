import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional


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


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Experimental collision mesh process: use trimesh's VHACD wrapper "
            "to decompose a mesh, then export one STL by joining parts, running "
            "Manifold boolean union, or sending the parts to Blender."
        )
    )
    parser.add_argument("input", type=Path,
                        help="Input mesh file or directory.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for generated STL files. Default: input_dir/trimesh_vhacd.",
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
        "--finalizer",
        choices=("joined", "manifold", "blender"),
        default="joined",
        help=(
            "How to turn VHACD parts into the final STL. joined keeps one file "
            "with multiple hull islands; manifold runs trimesh boolean union; "
            "blender uses the existing Blender union/remesh helper. Default: joined."
        ),
    )
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="Keep each VHACD convex hull as an STL under _parts/ for inspection.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep intermediate STL files under _work/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned work without writing files or running VHACD/finalizers.",
    )

    vhacd = parser.add_argument_group("trimesh/VHACD parameters")
    vhacd.add_argument(
        "--max-convex-hulls",
        type=int,
        default=16,
        help="VHACD maximum number of convex hulls. Default: 16.",
    )
    vhacd.add_argument(
        "--resolution",
        type=int,
        default=400000,
        help="VHACD voxel/sampling resolution. Default: 400000.",
    )
    vhacd.add_argument(
        "--minimum-volume-percent-error-allowed",
        type=float,
        default=1.0,
        help="VHACD minimum volume percent error allowed. Default: 1.0.",
    )
    vhacd.add_argument(
        "--max-recursion-depth",
        type=int,
        default=10,
        help="VHACD maximum recursion depth. Default: 10.",
    )
    vhacd.add_argument(
        "--shrink-wrap",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="VHACD shrinkWrap parameter. Default: true.",
    )
    vhacd.add_argument(
        "--fill-mode",
        default="flood",
        help='VHACD fillMode parameter. Common value: "flood". Default: flood.',
    )
    vhacd.add_argument(
        "--max-num-vertices-per-ch",
        type=int,
        default=64,
        help="VHACD maximum vertices per convex hull. Default: 64.",
    )
    vhacd.add_argument(
        "--async-acd",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="VHACD asyncACD parameter. Default: true.",
    )
    vhacd.add_argument(
        "--min-edge-length",
        type=int,
        default=2,
        help="VHACD minEdgeLength parameter. Default: 2.",
    )
    vhacd.add_argument(
        "--find-best-plane",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help="VHACD findBestPlane parameter. Default: false.",
    )

    manifold = parser.add_argument_group("Manifold finalizer")
    manifold.add_argument(
        "--manifold-check-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Pass check_volume to trimesh.boolean.union for Manifold. Default: "
            "false, because VHACD parts are expected to be convex volumes."
        ),
    )

    blender = parser.add_argument_group("Blender finalizer")
    blender.add_argument(
        "--blender",
        default="blender",
        help="Path to Blender executable, or blender if it is on PATH.",
    )
    blender.add_argument(
        "--union-remesh-script",
        type=Path,
        default=Path(__file__).with_name("blender_coacd_union_remesh.py"),
        help="Path to the Blender union/remesh helper script.",
    )
    blender.add_argument(
        "--blender-boolean-union",
        action="store_true",
        help="Ask Blender to Boolean-union hull objects before voxel remesh.",
    )
    blender.add_argument(
        "--voxel-remesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Ask Blender to voxel-remesh the merged hulls. Default: true.",
    )
    blender.add_argument(
        "--voxel-size",
        type=float,
        default=0.003,
        help="Blender voxel remesh size in mesh units. Default: 0.003.",
    )
    blender.add_argument(
        "--adaptivity",
        type=float,
        default=0.0,
        help="Blender voxel remesh adaptivity. Default: 0.0.",
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


def resolve_output_stl(input_mesh: Path, input_root: Path, output_root: Path):
    if input_root.is_dir():
        rel_parent = input_mesh.parent.relative_to(input_root)
        return output_root / rel_parent / f"{input_mesh.stem}.stl"

    return output_root / f"{input_mesh.stem}.stl"


def format_command(command):
    return " ".join(f'"{part}"' if " " in str(part) else str(part) for part in command)


def require_python_modules(args):
    missing = []
    try:
        import trimesh  # noqa: F401
    except ModuleNotFoundError:
        missing.append("trimesh")

    try:
        import vhacdx  # noqa: F401
    except ModuleNotFoundError:
        missing.append("vhacdx")

    if args.finalizer == "manifold":
        try:
            import manifold3d  # noqa: F401
        except ModuleNotFoundError:
            missing.append("manifold3d")

    if missing:
        raise SystemExit(
            "Missing Python dependency: "
            + ", ".join(missing)
            + "\nInstall them in the local venv with: .venv/bin/python -m pip install "
            + " ".join(missing)
        )


def vhacd_kwargs(args):
    return {
        "maxConvexHulls": args.max_convex_hulls,
        "resolution": args.resolution,
        "minimumVolumePercentErrorAllowed": args.minimum_volume_percent_error_allowed,
        "maxRecursionDepth": args.max_recursion_depth,
        "shrinkWrap": args.shrink_wrap,
        "fillMode": args.fill_mode,
        "maxNumVerticesPerCH": args.max_num_vertices_per_ch,
        "asyncACD": args.async_acd,
        "minEdgeLength": args.min_edge_length,
        "findBestPlane": args.find_best_plane,
    }


def run_vhacd(args, input_mesh: Path):
    import trimesh
    from trimesh.decomposition import convex_decomposition

    source_mesh = trimesh.load(input_mesh, force="mesh", process=True)
    part_args = convex_decomposition(source_mesh, **vhacd_kwargs(args))
    if not part_args:
        raise RuntimeError("trimesh convex_decomposition returned no hulls.")

    parts = [trimesh.Trimesh(**item, process=False) for item in part_args]
    return parts, source_mesh


def export_parts(parts, part_dir: Path, stem: str, keep_parts: bool):
    if not keep_parts:
        return []

    part_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, mesh in enumerate(parts):
        part_path = part_dir / f"{stem}_vhacd_{index:03d}.stl"
        mesh.export(part_path)
        paths.append(part_path)

    return paths


def export_joined(parts, output_stl: Path):
    import trimesh

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    joined = trimesh.util.concatenate(parts)
    joined.export(output_stl)
    return joined


def export_manifold_union(parts, output_stl: Path, check_volume: bool):
    import trimesh

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    result = trimesh.boolean.union(
        parts,
        engine="manifold",
        check_volume=check_volume,
    )
    if result is None:
        raise RuntimeError("trimesh.boolean.union returned None.")
    result.export(output_stl)
    return result


def build_blender_command(args, input_meshes, output_stl: Path):
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.union_remesh_script),
        "--",
        *[str(path) for path in input_meshes],
        str(output_stl),
        "--voxel-remesh",
        str(args.voxel_remesh).lower(),
        "--voxel-size",
        f"{args.voxel_size:.10g}",
        "--adaptivity",
        f"{args.adaptivity:.10g}",
    ]

    if args.blender_boolean_union:
        command.append("--boolean-union")

    return command


def export_blender(args, parts, work_part_dir: Path, raw_joined_stl: Path, output_stl: Path, stem: str):
    output_stl.parent.mkdir(parents=True, exist_ok=True)

    if args.blender_boolean_union:
        input_paths = export_parts(parts, work_part_dir, stem, keep_parts=True)
    else:
        export_joined(parts, raw_joined_stl)
        input_paths = [raw_joined_stl]

    command = build_blender_command(args, input_paths, output_stl)
    print(f"[INFO] Blender command: {format_command(command)}")
    subprocess.run(command, check=True)

    if not output_stl.exists():
        raise FileNotFoundError(
            f"Expected Blender STL was not produced: {output_stl}")

    return load_mesh(output_stl)


def load_mesh(path: Path):
    import trimesh

    return trimesh.load(path, force="mesh", process=False)


def load_exported_mesh(path: Path):
    import trimesh

    mesh = trimesh.load(path, force="mesh", process=True)
    mesh.merge_vertices()
    return mesh


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
    output_stl = resolve_output_stl(input_mesh, input_root, output_root)
    rel_stem = output_stl.relative_to(output_root).with_suffix("")
    part_dir = output_root / "_parts" / rel_stem
    work_part_dir = work_root / "_parts" / rel_stem
    raw_joined_stl = work_root / rel_stem.with_suffix(".joined.stl")
    manifest_path = output_stl.with_suffix(".trimesh_vhacd.json")

    print(f"\n[INFO] Processing: {input_mesh}")
    print(f"[INFO] Output STL: {output_stl}")
    print(f"[INFO] Finalizer: {args.finalizer}")
    print(f"[INFO] Keep parts: {args.keep_parts}")
    if args.keep_parts:
        print(f"[INFO] VHACD parts: {part_dir}")

    if args.dry_run:
        if args.finalizer == "blender":
            planned_inputs = ["<vhacd part STLs>"] if args.blender_boolean_union else [
                raw_joined_stl]
            command = build_blender_command(args, planned_inputs, output_stl)
            print(f"[INFO] Blender command: {format_command(command)}")
        return

    parts, source_mesh = run_vhacd(args, input_mesh)
    export_parts(parts, part_dir, input_mesh.stem, args.keep_parts)

    if args.finalizer == "joined":
        output_mesh = export_joined(parts, output_stl)
    elif args.finalizer == "manifold":
        output_mesh = export_manifold_union(
            parts,
            output_stl,
            check_volume=args.manifold_check_volume,
        )
    elif args.finalizer == "blender":
        output_mesh = export_blender(
            args,
            parts,
            work_part_dir,
            raw_joined_stl,
            output_stl,
            input_mesh.stem,
        )
    else:
        raise RuntimeError(f"Unknown finalizer: {args.finalizer}")

    if not output_stl.exists():
        raise FileNotFoundError(
            f"Expected output STL was not produced: {output_stl}")

    exported_mesh = load_exported_mesh(output_stl)
    manifest = {
        "input": str(input_mesh),
        "output_stl": str(output_stl),
        "part_count": len(parts),
        "finalizer": args.finalizer,
        "vhacd": vhacd_kwargs(args),
        "manifold": {
            "check_volume": args.manifold_check_volume,
        }
        if args.finalizer == "manifold"
        else None,
        "blender": {
            "boolean_union": args.blender_boolean_union,
            "voxel_remesh": args.voxel_remesh,
            "voxel_size": args.voxel_size,
            "adaptivity": args.adaptivity,
        }
        if args.finalizer == "blender"
        else None,
        "source_stats": mesh_stats(source_mesh),
        "pre_export_output_stats": mesh_stats(output_mesh),
        "exported_output_stats": mesh_stats(exported_mesh),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not args.keep_work:
        if raw_joined_stl.exists():
            raw_joined_stl.unlink()
        if work_part_dir.exists():
            shutil.rmtree(work_part_dir)

    print(f"[INFO] VHACD hull count: {len(parts)}")
    print(f"[INFO] Exported output stats: {manifest['exported_output_stats']}")
    print(f"[INFO] Manifest: {manifest_path}")


def main():
    args = parse_args()
    input_path = args.input.resolve()
    args.union_remesh_script = args.union_remesh_script.resolve()
    extensions = parse_extensions(args.extensions)
    input_base = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_base / "trimesh_vhacd"
    )
    work_root = output_root / "_work"
    excluded_roots = (
        output_root,
        input_base / "processed",
        input_base / "source",
        input_base / "remeshed",
        input_base / "coacd_merged",
    )

    if args.finalizer == "blender" and not args.union_remesh_script.is_file():
        raise SystemExit(
            f"Blender helper script does not exist: {args.union_remesh_script}")

    if not args.dry_run:
        require_python_modules(args)

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
    print(f"[INFO] Extensions: {', '.join(extensions)}")
    print(f"[INFO] Mesh count: {len(mesh_files)}")
    print(f"[INFO] Finalizer: {args.finalizer}")
    print(
        "[INFO] VHACD params: "
        f"maxConvexHulls={args.max_convex_hulls}, resolution={args.resolution}, "
        f"maxNumVerticesPerCH={args.max_num_vertices_per_ch}"
    )

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
