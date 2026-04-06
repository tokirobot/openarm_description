import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_mesh_utils import (  # noqa: E402
    clear_scene,
    export_mesh,
    import_mesh,
    iter_mesh_inputs,
    mesh_summary,
    output_path_for_input,
    parse_mesh_extensions,
    select_mesh_objects,
    shade_smooth_objects,
    smooth_mesh_objects,
    triangulate_objects,
)


def parse_bool(value):
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected true/false, got {value!r}.")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(
        description="Smooth STL/OBJ meshes with conservative topology smoothing."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input STL/OBJ file or directory.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help=(
            "Output STL/OBJ path for file input, or output directory for "
            "directory input."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process mesh files recursively when input is a directory.",
    )
    parser.add_argument(
        "--extensions",
        default="stl,obj",
        help="Comma-separated extensions to process in directory mode. Default: stl,obj.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Smoothing pass count. Default: 1.",
    )
    parser.add_argument(
        "--lambda-factor",
        type=float,
        default=0.5,
        help="Interior vertex smoothing factor in [0, 1]. Default: 0.5.",
    )
    parser.add_argument(
        "--lambda-border",
        type=float,
        default=0.5,
        help="Boundary vertex smoothing factor in [0, 1]. Default: 0.5.",
    )
    parser.add_argument(
        "--preserve-volume",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Scale each closed object back to its original volume. Default: true.",
    )
    parser.add_argument(
        "--shade-smooth",
        action="store_true",
        help="Set Blender smooth shading before export.",
    )
    parser.add_argument(
        "--triangulate",
        action="store_true",
        help="Triangulate before export.",
    )
    return parser.parse_args(argv)


def smooth_one(input_mesh, output_mesh, args):
    clear_scene()
    import_mesh(input_mesh)
    objects = select_mesh_objects()
    before = mesh_summary(objects)
    smoothed_count, max_delta, average_delta = smooth_mesh_objects(
        objects,
        repeat=args.repeat,
        lambda_factor=args.lambda_factor,
        lambda_border=args.lambda_border,
        preserve_volume=args.preserve_volume,
    )
    if args.shade_smooth:
        shade_smooth_objects(objects)
    if args.triangulate:
        triangulate_objects(objects)
    after = mesh_summary(objects)
    export_mesh(output_mesh, objects)

    print(f"[INFO] Input mesh: {input_mesh}")
    print(f"[INFO] Output mesh: {output_mesh}")
    print(f"[INFO] Before: {before}")
    print(f"[INFO] After: {after}")
    print(f"[INFO] Smoothed objects: {smoothed_count}")
    print(f"[INFO] Max vertex delta: {max_delta:.10g}")
    print(f"[INFO] Average vertex delta: {average_delta:.10g}")


def main():
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    try:
        extensions = parse_mesh_extensions(args.extensions)
        input_meshes = iter_mesh_inputs(
            input_path,
            recursive=args.recursive,
            extensions=extensions,
            output_root=output_path if input_path.is_dir() else None,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    input_root = input_path if input_path.is_dir() else None
    print(f"[INFO] Planned smooth jobs: {len(input_meshes)}")
    for input_mesh in input_meshes:
        output = output_path_for_input(input_mesh, input_root, output_path).resolve()
        smooth_one(input_mesh.resolve(), output, args)

    print(f"[INFO] Completed smooth jobs: {len(input_meshes)}")


if __name__ == "__main__":
    main()
