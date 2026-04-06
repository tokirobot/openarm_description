import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_mesh_utils import (  # noqa: E402
    clean_mesh_object,
    clear_scene,
    export_mesh,
    fix_inverted_normals,
    import_mesh,
    iter_mesh_inputs,
    mesh_summary,
    output_path_for_input,
    parse_mesh_extensions,
    remove_internal_voids,
    select_mesh_objects,
    self_intersection_summary,
    shade_smooth_objects,
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
        description=(
            "Repair STL/OBJ meshes: clean loose geometry, fill boundary holes, "
            "remove internal void islands, recalculate normals, and normalize "
            "inverted shells."
        )
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
        "--normal-only",
        action="store_true",
        help=(
            "Only fix inverted shells and recalculate normals. This disables "
            "loose/degenerate cleanup, hole filling, vertex merging, and "
            "internal void removal."
        ),
    )
    parser.add_argument(
        "--delete-loose",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Delete loose vertices/edges. Default: true.",
    )
    parser.add_argument(
        "--dissolve-degenerate",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Dissolve degenerate faces/edges. Default: true.",
    )
    parser.add_argument(
        "--merge-distance",
        type=float,
        default=0.0,
        help="Merge vertices closer than this distance. 0 disables it.",
    )
    parser.add_argument(
        "--fill-holes",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Fill boundary holes. Default: true.",
    )
    parser.add_argument(
        "--hole-sides",
        type=int,
        default=0,
        help="Maximum sides for hole filling. 0 lets Blender fill all sizes.",
    )
    parser.add_argument(
        "--remove-internal-voids",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Remove loose islands with opposite signed volume. Default: true.",
    )
    parser.add_argument(
        "--internal-void-volume-epsilon",
        type=float,
        default=1e-6,
        help="Signed-volume tolerance for internal void removal. Default: 1e-6.",
    )
    parser.add_argument(
        "--fix-inverted-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Flip remaining negative-volume islands. Default: true.",
    )
    parser.add_argument(
        "--recalculate-normals",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help=(
            "Run Blender normals_make_consistent on repaired mesh islands before "
            "export. Default: true."
        ),
    )
    parser.add_argument(
        "--normal-volume-epsilon",
        type=float,
        default=1e-6,
        help="Signed-volume tolerance for inverted normal detection. Default: 1e-6.",
    )
    parser.add_argument(
        "--triangulate",
        action="store_true",
        help="Triangulate before export.",
    )
    parser.add_argument(
        "--shade-smooth",
        action="store_true",
        help=(
            "Set Blender smooth shading before export. This changes display "
            "normals only and does not change vertex positions."
        ),
    )
    parser.add_argument(
        "--check-self-intersections",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Report non-adjacent triangle intersections after repair. "
            "Default: false."
        ),
    )
    parser.add_argument(
        "--fail-on-self-intersections",
        type=parse_bool,
        nargs="?",
        const=True,
        default=False,
        metavar="true|false",
        help=(
            "Exit with an error when --check-self-intersections finds any "
            "self-intersecting triangles. Default: false."
        ),
    )
    return parser.parse_args(argv)


def repair_one(input_mesh, output_mesh, args):
    delete_loose = False if args.normal_only else args.delete_loose
    dissolve_degenerate = False if args.normal_only else args.dissolve_degenerate
    merge_distance = 0.0 if args.normal_only else args.merge_distance
    fill_holes = False if args.normal_only else args.fill_holes
    remove_voids = False if args.normal_only else args.remove_internal_voids
    fix_normals = True if args.normal_only else args.fix_inverted_normals
    recalculate_normals = True if args.normal_only else args.recalculate_normals

    clear_scene()
    import_mesh(input_mesh)
    objects = select_mesh_objects()
    before = mesh_summary(objects)

    clean_reports = []
    for obj in list(objects):
        clean_before, clean_after = clean_mesh_object(
            obj,
            delete_loose=delete_loose,
            dissolve_degenerate=dissolve_degenerate,
            merge_distance=merge_distance,
            fill_holes=fill_holes,
            hole_sides=args.hole_sides,
            recalc_normals=False,
        )
        clean_reports.append((obj.name, clean_before, clean_after))

    objects = select_mesh_objects()
    removed_voids = []
    flipped_normals = []
    if remove_voids:
        objects, removed_voids = remove_internal_voids(
            objects,
            volume_epsilon=args.internal_void_volume_epsilon,
        )
    if fix_normals:
        objects, flipped_normals = fix_inverted_normals(
            objects,
            volume_epsilon=args.normal_volume_epsilon,
        )
    for obj in list(objects):
        clean_mesh_object(
            obj,
            delete_loose=delete_loose,
            dissolve_degenerate=dissolve_degenerate,
            merge_distance=0.0,
            fill_holes=False,
            hole_sides=args.hole_sides,
            recalc_normals=recalculate_normals,
        )
    objects = select_mesh_objects()
    shaded_count = 0
    if args.shade_smooth:
        shaded_count = shade_smooth_objects(objects)
    if args.triangulate:
        triangulate_objects(objects)
    after = mesh_summary(objects)
    self_intersections = None
    if args.check_self_intersections or args.fail_on_self_intersections:
        self_intersections = self_intersection_summary(objects)

    print(f"[INFO] Input mesh: {input_mesh}")
    print(f"[INFO] Output mesh: {output_mesh}")
    print(f"[INFO] Before: {before}")
    print(f"[INFO] After: {after}")
    print(f"[INFO] Cleaned objects: {len(clean_reports)}")
    for name, clean_before, clean_after in clean_reports:
        print(f"[INFO]   - {name}: {clean_before} -> {clean_after}")
    print(f"[INFO] Removed internal void islands: {len(removed_voids)}")
    for name, volume in removed_voids:
        print(f"[INFO]   - {name}: signed_volume={volume:.10g}")
    print(f"[INFO] Fixed inverted-normal islands: {len(flipped_normals)}")
    for name, old_volume, new_volume in flipped_normals:
        print(
            "[INFO]   - "
            f"{name}: signed_volume={old_volume:.10g} -> {new_volume:.10g}"
        )
    if args.normal_only:
        print("[INFO] Normal-only mode enabled")
    if recalculate_normals:
        print("[INFO] Recalculated mesh normals before export")
    if args.shade_smooth:
        print(f"[INFO] Shade smooth objects: {shaded_count}")
    if self_intersections is not None:
        print(
            "[INFO] Self-intersections: "
            f"pairs={self_intersections['self_intersection_pairs']}, "
            f"faces={self_intersections['self_intersection_faces']}"
        )
        for report in self_intersections["objects"]:
            print(
                "[INFO]   - "
                f"{report['object']}: faces={report['faces']}, "
                f"pairs={report['self_intersection_pairs']}, "
                f"intersecting_faces={report['self_intersection_faces']}"
            )
        if (
            args.fail_on_self_intersections
            and self_intersections["self_intersection_pairs"] > 0
        ):
            raise SystemExit("Self-intersections were detected.")

    export_mesh(output_mesh, objects)


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
    print(f"[INFO] Planned repair jobs: {len(input_meshes)}")
    for input_mesh in input_meshes:
        output = output_path_for_input(input_mesh, input_root, output_path).resolve()
        repair_one(input_mesh.resolve(), output, args)

    print(f"[INFO] Completed repair jobs: {len(input_meshes)}")


if __name__ == "__main__":
    main()
