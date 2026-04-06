import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_mesh_utils import (  # noqa: E402
    clear_scene,
    decimate_mesh_objects,
    export_mesh,
    import_mesh,
    iter_mesh_inputs,
    mesh_summary,
    output_path_for_input,
    parse_mesh_extensions,
    select_mesh_objects,
    triangulate_objects,
)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(
        description="Reduce STL/OBJ face count with Blender Decimate Collapse."
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
        "--ratio",
        type=float,
        default=0.5,
        help="Decimate ratio in [0.01, 1.0]. Default: 0.5.",
    )
    parser.add_argument(
        "--max-faces",
        type=int,
        default=0,
        help="Optional maximum face count per mesh object. 0 disables it.",
    )
    parser.add_argument(
        "--triangulate",
        action="store_true",
        help="Triangulate before export.",
    )
    return parser.parse_args(argv)


def decimate_one(input_mesh, output_mesh, args):
    clear_scene()
    import_mesh(input_mesh)
    objects = select_mesh_objects()
    before = mesh_summary(objects)
    objects, decimated = decimate_mesh_objects(
        objects,
        ratio=args.ratio,
        max_faces=args.max_faces,
    )
    if args.triangulate:
        triangulate_objects(objects)
    after = mesh_summary(objects)
    export_mesh(output_mesh, objects)

    print(f"[INFO] Input mesh: {input_mesh}")
    print(f"[INFO] Output mesh: {output_mesh}")
    print(f"[INFO] Before: {before}")
    print(f"[INFO] After: {after}")
    print(f"[INFO] Decimated objects: {len(decimated)}")
    for name, before_faces, after_faces, object_ratio in decimated:
        print(
            "[INFO]   - "
            f"{name}: faces={before_faces}->{after_faces}, ratio={object_ratio:.10g}"
        )
    return before, after


def main():
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    try:
        extensions = parse_mesh_extensions(args.extensions)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    input_root = input_path if input_path.is_dir() else None
    try:
        input_meshes = iter_mesh_inputs(
            input_path,
            recursive=args.recursive,
            extensions=extensions,
            output_root=output_path if input_root is not None else None,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"[INFO] Planned decimate jobs: {len(input_meshes)}")
    for input_mesh in input_meshes:
        output = output_path_for_input(input_mesh, input_root, output_path).resolve()
        decimate_one(input_mesh.resolve(), output, args)

    print(f"[INFO] Completed decimate jobs: {len(input_meshes)}")


if __name__ == "__main__":
    main()
