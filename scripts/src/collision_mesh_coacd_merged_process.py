import argparse
import json
import shutil
import subprocess
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


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Experimental collision mesh process: run CoACD, merge the convex "
            "parts, then export one STL by joining parts, using Manifold union, "
            "or using Blender union/voxel remesh."
        )
    )
    parser.add_argument("input", type=Path,
                        help="Input mesh file or directory.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for generated single STL files. Default: input_dir/coacd_merged.",
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
        choices=("blender", "joined", "manifold"),
        default="blender",
        help=(
            "How to turn CoACD parts into the final STL. blender preserves the "
            "original behavior; joined concatenates hulls into one STL file; "
            "manifold runs trimesh boolean union with the Manifold engine. "
            "Default: blender."
        ),
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Path to Blender executable, or blender if it is on PATH.",
    )
    parser.add_argument(
        "--union-remesh-script",
        type=Path,
        default=Path(__file__).with_name("blender_coacd_union_remesh.py"),
        help="Path to the Blender union/remesh processor script.",
    )
    parser.add_argument(
        "--skip-blender",
        action="store_true",
        help=(
            "Only export the raw concatenated CoACD hull STL. This keeps one "
            "file, but it is multiple mesh islands and is not a clean union. "
            "Equivalent to --finalizer joined."
        ),
    )
    parser.add_argument(
        "--manifold-check-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Pass check_volume to trimesh.boolean.union for --finalizer manifold. "
            "Default: false, because CoACD parts are expected to be convex volumes."
        ),
    )
    parser.add_argument(
        "--boolean-union",
        action="store_true",
        help=(
            "Ask Blender to Boolean-union hull objects before voxel remesh. "
            "Default is voxel remesh only, which is usually more robust."
        ),
    )
    parser.add_argument(
        "--boolean-solver",
        choices=("EXACT", "FAST"),
        default="EXACT",
        help="Blender Boolean solver used with --boolean-union. Default: EXACT.",
    )
    parser.add_argument(
        "--voxel-remesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Ask Blender to voxel-remesh the merged hulls. Default: true.",
    )
    parser.add_argument(
        "--voxel-size",
        type=float,
        default=0.001,
        help="Blender voxel remesh size in mesh units. Default: 0.001.",
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
        help="Shade the Blender output smooth before STL export. Default: false.",
    )
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="Keep each CoACD convex hull as an STL under _parts/ for inspection.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep the raw concatenated hull STL under _work/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned work without writing files or running CoACD/Blender.",
    )

    coacd = parser.add_argument_group("CoACD parameters")
    coacd.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help=(
            "CoACD concavity threshold. Smaller values produce more hulls and "
            "more detail. Default: 0.05."
        ),
    )
    coacd.add_argument(
        "--real-metric",
        action="store_true",
        help=(
            "Pass CoACD real_metric=True so --threshold is interpreted in mesh "
            "units. Requires a recent CoACD version."
        ),
    )
    coacd.add_argument(
        "--max-convex-hull",
        type=int,
        default=-1,
        help="Maximum number of convex hulls. -1 means no limit. Default: -1.",
    )
    coacd.add_argument(
        "--preprocess-mode",
        choices=("auto", "on", "off"),
        default="auto",
        help="CoACD preprocessing mode. Default: auto.",
    )
    coacd.add_argument(
        "--preprocess-resolution",
        type=int,
        default=50,
        help="CoACD manifold preprocessing resolution. Default: 50.",
    )
    coacd.add_argument(
        "--resolution",
        type=int,
        default=2000,
        help="CoACD sampling resolution. Default: 2000.",
    )
    coacd.add_argument(
        "--mcts-nodes",
        type=int,
        default=20,
        help="CoACD MCTS node count. Default: 20.",
    )
    coacd.add_argument(
        "--mcts-iterations",
        type=int,
        default=150,
        help="CoACD MCTS iteration count. Default: 150.",
    )
    coacd.add_argument(
        "--mcts-max-depth",
        type=int,
        default=3,
        help="CoACD MCTS maximum depth. Default: 3.",
    )
    coacd.add_argument(
        "--pca",
        action="store_true",
        help="Enable CoACD PCA alignment.",
    )
    coacd.add_argument(
        "--merge",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Enable CoACD adjacent-hull merge. Default: true.",
    )
    coacd.add_argument(
        "--seed",
        type=int,
        default=0,
        help="CoACD random seed. Default: 0.",
    )
    coacd.add_argument(
        "--verbose-coacd",
        action="store_true",
        help="Set CoACD log level to info.",
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
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def require_python_modules(args):
    missing = []
    try:
        import trimesh  # noqa: F401
    except ModuleNotFoundError:
        missing.append("trimesh")

    try:
        import coacd  # noqa: F401
    except ModuleNotFoundError:
        missing.append("coacd")

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


def coacd_kwargs(args):
    kwargs = {
        "threshold": args.threshold,
        "max_convex_hull": args.max_convex_hull,
        "preprocess_mode": args.preprocess_mode,
        "preprocess_resolution": args.preprocess_resolution,
        "resolution": args.resolution,
        "mcts_nodes": args.mcts_nodes,
        "mcts_iterations": args.mcts_iterations,
        "mcts_max_depth": args.mcts_max_depth,
        "pca": args.pca,
        "merge": args.merge,
        "seed": args.seed,
    }
    if args.real_metric:
        kwargs["real_metric"] = True
    return kwargs


def run_coacd_decomposition(args, input_mesh: Path):
    import coacd
    import trimesh

    coacd.set_log_level("info" if args.verbose_coacd else "warn")

    mesh = trimesh.load(input_mesh, force="mesh", process=True)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    coacd_mesh = coacd.Mesh(vertices, faces)

    kwargs = coacd_kwargs(args)
    try:
        parts = coacd.run_coacd(coacd_mesh, **kwargs)
    except TypeError as exc:
        if "real_metric" in kwargs:
            print(
                "[WARN] Installed CoACD does not appear to support real_metric; "
                "retrying without it."
            )
            kwargs.pop("real_metric")
            parts = coacd.run_coacd(coacd_mesh, **kwargs)
        else:
            raise exc

    return parts, mesh


def export_parts(parts, part_dir: Path, stem: str, keep_parts: bool):
    import trimesh

    meshes = []
    for index, (vertices, faces) in enumerate(parts):
        part_mesh = trimesh.Trimesh(
            vertices=vertices, faces=faces, process=False)
        meshes.append(part_mesh)

        if keep_parts:
            part_dir.mkdir(parents=True, exist_ok=True)
            part_path = part_dir / f"{stem}_ch_{index:03d}.stl"
            part_mesh.export(part_path)

    return meshes


def export_raw_merged(meshes, raw_merged_stl: Path):
    import trimesh

    raw_merged_stl.parent.mkdir(parents=True, exist_ok=True)
    merged = trimesh.util.concatenate(meshes)
    merged.export(raw_merged_stl)
    return merged


def export_manifold_union(meshes, output_stl: Path, check_volume: bool):
    import trimesh

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    result = trimesh.boolean.union(
        meshes,
        engine="manifold",
        check_volume=check_volume,
    )
    if result is None:
        raise RuntimeError("trimesh.boolean.union returned None.")
    result.export(output_stl)
    return result


def build_blender_command(args, input_meshes, output_stl: Path):
    input_args = [str(path) for path in input_meshes]
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.union_remesh_script),
        "--",
        *input_args,
        str(output_stl),
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
        command.extend(
            ["--boolean-union", "--boolean-solver", args.boolean_solver])

    return command


def mesh_stats(mesh):
    components = mesh.split(only_watertight=False)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "is_watertight": bool(mesh.is_watertight),
        "component_count": int(len(components)),
        "volume": float(mesh.volume) if mesh.is_watertight else None,
    }


def load_exported_mesh(path: Path):
    import trimesh

    mesh = trimesh.load(path, force="mesh", process=True)
    mesh.merge_vertices()
    return mesh


def process_one(args, input_mesh: Path, input_root: Path, output_root: Path, work_root: Path):
    output_stl = resolve_output_stl(input_mesh, input_root, output_root)
    rel_stem = output_stl.relative_to(output_root).with_suffix("")
    part_dir = output_root / "_parts" / rel_stem
    work_part_dir = work_root / "_parts" / rel_stem
    raw_merged_stl = work_root / rel_stem.with_suffix(".raw_merged.stl")
    manifest_path = output_stl.with_suffix(".coacd.json")

    print(f"\n[INFO] Processing: {input_mesh}")
    print(f"[INFO] Output STL: {output_stl}")
    print(f"[INFO] Finalizer: {args.finalizer}")
    print(f"[INFO] Raw merged STL: {raw_merged_stl}")
    print(f"[INFO] Keep CoACD parts: {args.keep_parts}")
    if args.keep_parts:
        print(f"[INFO] CoACD parts: {part_dir}")

    if args.dry_run:
        planned_inputs = ["<coacd part STLs>"] if args.boolean_union else [
            raw_merged_stl]
        if args.finalizer == "blender":
            blender_command = build_blender_command(
                args, planned_inputs, output_stl)
            print(f"[INFO] Blender command: {format_command(blender_command)}")
        return

    parts, source_mesh = run_coacd_decomposition(args, input_mesh)
    if not parts:
        raise RuntimeError("CoACD returned no convex hulls.")

    written_part_dir = part_dir if args.keep_parts else work_part_dir
    part_meshes = export_parts(
        parts,
        written_part_dir,
        input_mesh.stem,
        args.keep_parts or (
            args.finalizer == "blender" and args.boolean_union),
    )
    raw_merged = export_raw_merged(part_meshes, raw_merged_stl)

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    if args.finalizer == "joined":
        shutil.copy2(raw_merged_stl, output_stl)
        output_mesh = raw_merged
    elif args.finalizer == "manifold":
        output_mesh = export_manifold_union(
            part_meshes,
            output_stl,
            check_volume=args.manifold_check_volume,
        )
    elif args.finalizer == "blender":
        blender_inputs = (
            sorted(written_part_dir.glob(f"{input_mesh.stem}_ch_*.stl"))
            if args.boolean_union
            else [raw_merged_stl]
        )
        if not blender_inputs:
            raise RuntimeError(
                "No CoACD part STLs were written for Boolean union.")
        blender_command = build_blender_command(
            args, blender_inputs, output_stl)
        print(f"[INFO] Blender command: {format_command(blender_command)}")
        subprocess.run(blender_command, check=True)
        output_mesh = load_exported_mesh(output_stl)
    else:
        raise RuntimeError(f"Unknown finalizer: {args.finalizer}")

    if not output_stl.exists():
        raise FileNotFoundError(
            f"Expected output STL was not produced: {output_stl}")

    exported_mesh = load_exported_mesh(output_stl)

    manifest = {
        "input": str(input_mesh),
        "output_stl": str(output_stl),
        "part_count": len(part_meshes),
        "finalizer": args.finalizer,
        "coacd": coacd_kwargs(args),
        "blender": None
        if args.finalizer != "blender"
        else {
            "boolean_union": args.boolean_union,
            "boolean_solver": args.boolean_solver,
            "voxel_remesh": args.voxel_remesh,
            "voxel_size": args.voxel_size,
            "adaptivity": args.adaptivity,
            "smooth_normals": args.smooth_normals,
        },
        "manifold": {
            "check_volume": args.manifold_check_volume,
        }
        if args.finalizer == "manifold"
        else None,
        "source_stats": mesh_stats(source_mesh),
        "raw_merged_stats": mesh_stats(raw_merged),
        "pre_export_output_stats": mesh_stats(output_mesh),
        "exported_output_stats": mesh_stats(exported_mesh),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not args.keep_work and raw_merged_stl.exists():
        raw_merged_stl.unlink()
    if args.boolean_union and args.finalizer == "blender" and not args.keep_parts:
        for part_path in sorted(work_part_dir.glob(f"{input_mesh.stem}_ch_*.stl")):
            part_path.unlink()

    print(f"[INFO] CoACD hull count: {len(part_meshes)}")
    print(f"[INFO] Exported output stats: {manifest['exported_output_stats']}")
    print(f"[INFO] Manifest: {manifest_path}")


def main():
    args = parse_args()
    if args.skip_blender:
        args.finalizer = "joined"
    input_path = args.input.resolve()
    args.union_remesh_script = args.union_remesh_script.resolve()
    extensions = parse_extensions(args.extensions)
    input_base = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_base / "coacd_merged"
    )
    work_root = output_root / "_work"
    excluded_roots = (
        output_root,
        input_base / "processed",
        input_base / "source",
        input_base / "remeshed",
    )

    if args.finalizer == "blender" and not args.union_remesh_script.is_file():
        raise SystemExit(
            f"Blender union/remesh script does not exist: {args.union_remesh_script}"
        )

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
    print(
        "[INFO] CoACD params: "
        f"threshold={args.threshold}, max_convex_hull={args.max_convex_hull}, "
        f"preprocess_mode={args.preprocess_mode}, merge={args.merge}, "
        f"real_metric={args.real_metric}"
    )
    print(
        "[INFO] Finalization: "
        f"finalizer={args.finalizer}, boolean_union={args.boolean_union}, "
        f"voxel_remesh={args.voxel_remesh}, voxel_size={args.voxel_size}"
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
