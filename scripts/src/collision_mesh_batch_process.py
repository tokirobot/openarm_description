import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Optional


SUPPORTED_EXTENSIONS = (".dae", ".obj", ".stl")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Batch build STL collision meshes with Blender convex hull. "
            "Without --replace, outputs are written under processed/. "
            "With --replace, only STL inputs are allowed, source STLs are backed "
            "up under source/, and source STLs are replaced."
        )
    )
    parser.add_argument("input", type=Path,
                        help="Input mesh file or directory.")
    parser.add_argument(
        "--blender",
        default="blender",
        help="Path to Blender executable, or blender if it is on PATH.",
    )
    parser.add_argument(
        "--processor",
        type=Path,
        default=Path(__file__).with_name("collision_mesh_convex_hull.py"),
        help="Path to the Blender convex hull processor script.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for generated STL files. Default: input_dir/processed.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process mesh files recursively when input is a directory.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace source STL files and back up originals under source/.",
    )
    parser.add_argument(
        "--extensions",
        default="dae,obj,stl",
        help="Comma-separated extensions to process in directory mode. Default: dae,obj,stl.",
    )
    parser.add_argument(
        "--per-node-hull",
        action="store_true",
        help=(
            "Pass through to Blender: build a convex hull for each imported "
            "mesh object first, then join the hulls. Intended for DAE node meshes."
        ),
    )
    parser.add_argument(
        "--split-axis",
        choices=("x", "y", "z", "X", "Y", "Z"),
        default=None,
        help=(
            "Pass through to Blender: cut the joined mesh by a plane "
            "perpendicular to this axis before building hulls."
        ),
    )
    parser.add_argument(
        "--split-direction",
        choices=("positive", "negative", "pos", "neg", "+", "-"),
        default=None,
        help=(
            "Pass through to Blender: side whose farthest point is used as "
            "the cut origin."
        ),
    )
    parser.add_argument(
        "--split-offset",
        type=float,
        default=None,
        help=(
            "Pass through to Blender: distance from selected axis extreme "
            "toward the model interior where the cut plane is placed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned Blender commands without changing files.",
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


def unique_path(path: Path):
    if not path.exists():
        return path

    for i in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{i:03d}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find an available path for {path}")


def is_under(path: Path, root: Optional[Path]):
    if root is None:
        return False
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def iter_mesh_files(
    input_path: Path,
    recursive: bool,
    extensions,
    processed_root: Optional[Path],
    source_root: Path,
):
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
        if is_under(path, processed_root) or is_under(path, source_root):
            continue
        files.append(path)

    return sorted(files)


def resolve_output_stl(input_mesh: Path, input_root: Path, output_root: Path, replace: bool):
    if replace:
        return input_mesh

    if input_root.is_dir():
        rel_parent = input_mesh.parent.relative_to(input_root)
        return output_root / rel_parent / f"{input_mesh.stem}.stl"

    return output_root / f"{input_mesh.stem}.stl"


def resolve_source_backup_path(input_mesh: Path, input_root: Path, source_root: Path):
    if input_root.is_dir():
        rel_path = input_mesh.relative_to(input_root)
        return unique_path(source_root / rel_path)

    return unique_path(source_root / input_mesh.name)


def build_blender_command(args, input_mesh: Path, output_stl: Path):
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.processor),
        "--",
        str(input_mesh),
        str(output_stl),
    ]

    if args.per_node_hull:
        command.append("--per-node-hull")

    if args.split_axis is not None:
        command.extend(
            [
                "--split-axis",
                str(args.split_axis),
                "--split-direction",
                str(args.split_direction),
                "--split-offset",
                f"{args.split_offset:.10g}",
            ]
        )

    return command


def replace_source_stl(source_stl: Path, result_stl: Path, backup_stl: Path):
    tmp_replacement = source_stl.with_name(f".{source_stl.stem}.stl.tmp")

    backup_stl.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_stl, backup_stl)

    try:
        shutil.copy2(result_stl, tmp_replacement)
        tmp_replacement.replace(source_stl)
    except Exception:
        if tmp_replacement.exists():
            tmp_replacement.unlink()
        raise

    return backup_stl


def format_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def process_one(args, input_mesh: Path, input_root: Path, output_root: Path, source_root: Path):
    if args.replace and input_mesh.suffix.lower() != ".stl":
        raise RuntimeError(f"--replace only supports STL inputs: {input_mesh}")

    output_stl = resolve_output_stl(
        input_mesh, input_root, output_root, args.replace)
    blender_output_stl = (
        unique_path(input_mesh.with_name(
            f".{input_mesh.stem}.convex_hull_result.stl"))
        if args.replace
        else output_stl
    )
    backup_stl = (
        resolve_source_backup_path(input_mesh, input_root, source_root)
        if args.replace
        else None
    )
    command = build_blender_command(args, input_mesh, blender_output_stl)

    print(f"\n[INFO] Processing: {input_mesh}")
    print(f"[INFO] Output STL: {output_stl}")
    if backup_stl is not None:
        print(f"[INFO] Source backup: {backup_stl}")
    print(f"[INFO] Blender command: {format_command(command)}")

    if args.dry_run:
        if args.replace:
            print(
                f"[DRY-RUN] Would replace {input_mesh} with {blender_output_stl}")
        return

    blender_output_stl.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)

    if not blender_output_stl.exists():
        raise FileNotFoundError(
            f"Expected Blender STL was not produced: {blender_output_stl}")

    if args.replace:
        backup = replace_source_stl(input_mesh, blender_output_stl, backup_stl)
        print(f"[INFO] Source backup: {backup}")
        print(f"[INFO] Replaced source STL: {input_mesh}")

        if blender_output_stl.exists():
            blender_output_stl.unlink()


def main():
    args = parse_args()
    input_path = args.input.resolve()
    args.processor = args.processor.resolve()
    extensions = parse_extensions(args.extensions)
    input_base = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_base / "processed"
    )
    source_root = input_base / "source"

    if not args.processor.is_file():
        raise SystemExit(f"Processor script does not exist: {args.processor}")
    split_values = [
        args.split_axis is not None,
        args.split_direction is not None,
        args.split_offset is not None,
    ]
    if any(split_values) and not all(split_values):
        raise SystemExit(
            "--split-axis, --split-direction, and --split-offset must be used together."
        )
    if args.split_axis is not None and args.replace:
        raise SystemExit("--replace cannot be combined with split cutting.")
    if args.split_axis is not None and args.per_node_hull:
        raise SystemExit("--per-node-hull cannot be combined with split cutting.")
    if args.split_offset is not None and args.split_offset <= 0:
        raise SystemExit("--split-offset must be greater than 0.")

    mesh_files = iter_mesh_files(
        input_path=input_path,
        recursive=args.recursive,
        extensions=extensions,
        processed_root=output_root,
        source_root=source_root,
    )

    if args.replace:
        non_stl = [path for path in mesh_files if path.suffix.lower()
                   != ".stl"]
        if non_stl:
            raise SystemExit(
                "--replace only supports STL inputs. Use --extensions stl.")

    if not mesh_files:
        print(f"[WARN] No mesh files found under {input_path}")
        return

    print(f"[INFO] Input: {input_path}")
    print(f"[INFO] Replace mode: {args.replace}")
    if not args.replace:
        print(f"[INFO] Output root: {output_root}")
    print(f"[INFO] Source root: {source_root}")
    print(f"[INFO] Extensions: {', '.join(extensions)}")
    print(f"[INFO] Per-node hull: {args.per_node_hull}")
    print(f"[INFO] Mesh count: {len(mesh_files)}")

    failures = []
    for mesh_path in mesh_files:
        try:
            process_one(
                args=args,
                input_mesh=mesh_path.resolve(),
                input_root=input_path,
                output_root=output_root,
                source_root=source_root,
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
