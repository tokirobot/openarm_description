import argparse
import subprocess
from pathlib import Path
from typing import Optional


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
            "Batch process STL collision meshes with OpenVDB vdb_tool. "
            "The script runs mesh2ls/close/ls2mesh, writes an intermediate OBJ, "
            "then uses Blender to convert that OBJ to STL."
        )
    )
    parser.add_argument("input", type=Path,
                        help="Input STL file or directory.")
    parser.add_argument(
        "--vdb-tool",
        default="vdb_tool",
        help="Path to vdb_tool executable, or vdb_tool if it is on PATH.",
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Path to Blender executable, or blender if it is on PATH.",
    )
    parser.add_argument(
        "--converter",
        type=Path,
        default=Path(__file__).with_name("blender_obj_to_stl.py"),
        help="Path to the Blender OBJ-to-STL converter script.",
    )
    parser.add_argument("--voxel", type=float, default=0.001)
    parser.add_argument("--width", type=int, default=23)
    parser.add_argument("--close-radius", type=int, default=18)
    parser.add_argument("--adapt", type=float, default=0.01)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for generated STL/OBJ files. Default: input_dir/remeshed.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process STL files recursively when input is a directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned vdb_tool commands without writing files.",
    )
    parser.add_argument(
        "--remove-internal-voids",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Ask the Blender converter to remove enclosed internal void "
            "islands from the OpenVDB OBJ before exporting STL. Default: true."
        ),
    )
    parser.add_argument(
        "--internal-void-volume-epsilon",
        type=float,
        default=1e-15,
        help=(
            "Minimum absolute signed volume for --remove-internal-voids. "
            "Passed through to the Blender converter."
        ),
    )
    parser.add_argument(
        "--fix-inverted-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Ask the Blender converter to flip negative-volume mesh islands "
            "so exported STL normals face outward. Default: true."
        ),
    )
    parser.add_argument(
        "--normal-volume-epsilon",
        type=float,
        default=1e-15,
        help=(
            "Minimum absolute signed volume for --fix-inverted-normals. "
            "Passed through to the Blender converter."
        ),
    )
    parser.add_argument(
        "--sync-processed-obj",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Overwrite the intermediate OpenVDB OBJ with the Blender-processed "
            "mesh when OBJ cleanup/normal fixing is enabled. Default: true."
        ),
    )
    parser.add_argument(
        "--smooth-mesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Apply topology-based smoothing after OBJ cleanup/normal fixing. "
            "Default: false."
        ),
    )
    parser.add_argument(
        "--smooth-repeat",
        type=int,
        default=5,
        help="Repeat count for --smooth-mesh. Default: 5.",
    )
    parser.add_argument(
        "--smooth-lambda-factor",
        type=float,
        default=0.6,
        help="Interior vertex smoothing factor. Default: 0.6.",
    )
    parser.add_argument(
        "--smooth-lambda-border",
        type=float,
        default=0.05,
        help="Boundary vertex smoothing factor. Default: 0.05.",
    )
    parser.add_argument(
        "--smooth-preserve-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Restore closed-mesh volume after smoothing. Default: true.",
    )
    parser.add_argument(
        "--decimate-mesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Apply Blender Decimate Collapse after smoothing. Default: false."
        ),
    )
    parser.add_argument(
        "--decimate-ratio",
        type=float,
        default=0.5,
        help="Decimate ratio for --decimate-mesh. Default: 0.5.",
    )
    parser.add_argument(
        "--decimate-max-faces",
        type=int,
        default=0,
        help=(
            "Optional per-object face-count cap for --decimate-mesh. "
            "0 disables it. Default: 0."
        ),
    )
    return parser.parse_args()


def iter_stl_files(
    input_path: Path,
    recursive: bool,
    excluded_roots,
):
    if input_path.is_file():
        if input_path.suffix.lower() != ".stl":
            raise SystemExit(f"Input file is not an STL: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise SystemExit(f"Input path does not exist: {input_path}")

    pattern = "**/*.stl" if recursive else "*.stl"
    files = []
    for path in input_path.glob(pattern):
        if not path.is_file():
            continue
        excluded = False
        for excluded_root in excluded_roots:
            if excluded_root is None:
                continue
            try:
                path.relative_to(excluded_root)
                excluded = True
                break
            except ValueError:
                pass
        if excluded:
            continue
        files.append(path)

    return sorted(files)


def first_matching_excluded_root(path: Path, excluded_roots):
    for root in excluded_roots:
        if root is None:
            continue
        try:
            path.relative_to(root)
            return root
        except ValueError:
            pass

    return None


def resolve_output_path(
    stl_path: Path,
    input_root: Path,
    output_root: Path,
):
    if input_root.is_dir():
        rel_parent = stl_path.parent.relative_to(input_root)
        return output_root / rel_parent / stl_path.name

    return output_root / stl_path.name


def build_vdb_command(args, input_stl: Path, output_obj: Path):
    return [
        str(args.vdb_tool),
        "-read",
        str(input_stl),
        "-mesh2ls",
        f"voxel={args.voxel:.10g}",
        f"width={args.width}",
        "-close",
        f"radius={args.close_radius}",
        # "-gauss",
        # "iter=1",
        # "size=1",
        "-ls2mesh",
        f"adapt={args.adapt:.10g}",
        "-write",
        str(output_obj),
    ]


def build_blender_command(args, input_obj: Path, output_stl: Path):
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.converter),
        "--",
        str(input_obj),
        str(output_stl),
    ]

    if args.remove_internal_voids:
        command.extend(
            [
                "--remove-internal-voids",
                "--internal-void-volume-epsilon",
                f"{args.internal_void_volume_epsilon:.10g}",
            ]
        )

    if args.fix_inverted_normals:
        command.extend(
            [
                "--fix-inverted-normals",
                "--normal-volume-epsilon",
                f"{args.normal_volume_epsilon:.10g}",
            ]
        )

    if args.smooth_mesh:
        command.extend(
            [
                "--smooth-mesh",
                "--smooth-repeat",
                str(args.smooth_repeat),
                "--smooth-lambda-factor",
                f"{args.smooth_lambda_factor:.10g}",
                "--smooth-lambda-border",
                f"{args.smooth_lambda_border:.10g}",
                "--smooth-preserve-volume",
                str(args.smooth_preserve_volume).lower(),
            ]
        )

    if args.decimate_mesh:
        command.extend(
            [
                "--decimate-mesh",
                "--decimate-ratio",
                f"{args.decimate_ratio:.10g}",
                "--decimate-max-faces",
                str(args.decimate_max_faces),
            ]
        )

    if args.sync_processed_obj and (
        args.remove_internal_voids
        or args.fix_inverted_normals
        or args.smooth_mesh
        or args.decimate_mesh
    ):
        command.extend(["--processed-obj", str(input_obj)])

    return command


def format_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def process_one(args, stl_path: Path, input_root: Path, output_root: Path):
    output_stl = resolve_output_path(
        stl_path=stl_path,
        input_root=input_root,
        output_root=output_root,
    )
    output_obj = output_stl.with_suffix(".obj")

    command = build_vdb_command(args, stl_path, output_obj)
    blender_command = build_blender_command(args, output_obj, output_stl)

    print(f"\n[INFO] Processing: {stl_path}")
    print(f"[INFO] Output OBJ: {output_obj}")
    print(f"[INFO] Output STL: {output_stl}")
    print(f"[INFO] VDB command: {format_command(command)}")
    print(f"[INFO] Blender command: {format_command(blender_command)}")

    if args.dry_run:
        return

    output_obj.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)

    if not output_obj.exists():
        raise FileNotFoundError(
            f"Expected vdb_tool OBJ was not produced: {output_obj}")

    output_stl.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(blender_command, check=True)

    if not output_stl.exists():
        raise FileNotFoundError(
            f"Expected Blender STL was not produced: {output_stl}")

    print(f"[INFO] Converted OBJ to STL with Blender: {output_stl}")


def main():
    args = parse_args()
    input_path = args.input.resolve()
    args.converter = args.converter.resolve()
    input_base = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_base / "remeshed"
    )
    excluded_roots = (output_root, input_base /
                      "processed", input_base / "source")

    if not args.converter.is_file():
        raise SystemExit(
            f"Blender converter script does not exist: {args.converter}")

    stl_files = iter_stl_files(
        input_path,
        args.recursive,
        excluded_roots=excluded_roots,
    )
    if not stl_files:
        excluded_root = first_matching_excluded_root(
            input_path, excluded_roots)
        if excluded_root is not None:
            print(
                "[WARN] Input path is under an excluded output/source directory: "
                f"{excluded_root}"
            )
            print(
                "[WARN] Files there are skipped to avoid reprocessing generated "
                "meshes or overwriting existing outputs."
            )
            if excluded_root == output_root and input_path != output_root:
                print(
                    "[WARN] With the current --output-root, generated OBJ/STL files "
                    "would be written under the output root and may overwrite "
                    "existing files with the same names."
                )
        print(f"[WARN] No STL files found under {input_path}")
        return

    print(f"[INFO] Input: {input_path}")
    print(f"[INFO] Output root: {output_root}")
    print(f"[INFO] STL count: {len(stl_files)}")
    print(
        "[INFO] VDB params: "
        f"voxel={args.voxel}, width={args.width}, "
        f"close_radius={args.close_radius}, adapt={args.adapt}"
    )

    failures = []
    for stl_path in stl_files:
        try:
            process_one(
                args=args,
                stl_path=stl_path.resolve(),
                input_root=input_path,
                output_root=output_root,
            )
        except Exception as exc:
            failures.append((stl_path, exc))
            print(f"[ERROR] Failed processing {stl_path}: {exc}")

    if failures:
        print("\n[ERROR] Batch completed with failures:")
        for path, exc in failures:
            print(f"  - {path}: {exc}")
        raise SystemExit(1)

    print("\n[INFO] Batch completed successfully.")


if __name__ == "__main__":
    main()
