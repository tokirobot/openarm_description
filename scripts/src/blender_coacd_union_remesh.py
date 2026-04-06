import argparse
import sys
from pathlib import Path

import bpy


SUPPORTED_INPUTS = {".stl", ".obj", ".dae", ".ply"}


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
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description=(
            "Convert a merged CoACD hull mesh into one closed STL with optional "
            "Boolean union and Blender voxel remesh."
        )
    )
    parser.add_argument("input_meshes", type=Path, nargs="+")
    parser.add_argument("output_stl", type=Path)
    parser.add_argument(
        "--boolean-union",
        action="store_true",
        help=(
            "Union separate imported mesh objects with Blender Boolean modifiers "
            "before voxel remeshing. This is slower and less robust than voxel "
            "remesh alone, but useful for experiments."
        ),
    )
    parser.add_argument(
        "--boolean-solver",
        choices=("EXACT", "FAST"),
        default="EXACT",
        help="Blender Boolean solver. Default: EXACT.",
    )
    parser.add_argument(
        "--voxel-remesh",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="true|false",
        help="Apply Blender voxel remesh after joining/unioning hulls. Default: true.",
    )
    parser.add_argument(
        "--voxel-size",
        type=float,
        default=0.001,
        help="Voxel size for Blender remesh. Default: 0.001.",
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
        help="Shade the remeshed object smooth before export. Default: false.",
    )
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_mesh(path: Path):
    suffix = path.suffix.lower()

    if suffix == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.stl(filepath=str(path))
        return

    if suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
        return

    if suffix == ".dae":
        if not hasattr(bpy.ops.wm, "collada_import"):
            raise RuntimeError(
                "This Blender build does not provide Collada import.")
        bpy.ops.wm.collada_import(filepath=str(path), import_units=True)
        return

    if suffix == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.ply(filepath=str(path))
        return

    raise RuntimeError(f"Unsupported input mesh format: {path.suffix}")


def mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def join_mesh_objects(objects, name):
    if not objects:
        raise RuntimeError("No mesh objects were imported.")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if len(objects) > 1:
        bpy.ops.object.join()

    joined = bpy.context.view_layer.objects.active
    joined.name = name
    joined.data.name = f"{name}_mesh"
    return joined


def clean_mesh_object(obj):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.delete_loose()
    try:
        bpy.ops.mesh.dissolve_degenerate()
    except Exception:
        pass
    try:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    except Exception:
        pass
    bpy.ops.object.mode_set(mode="OBJECT")


def boolean_union_objects(objects, solver):
    if not objects:
        raise RuntimeError("No mesh objects to union.")

    base = objects[0]
    bpy.ops.object.select_all(action="DESELECT")
    base.select_set(True)
    bpy.context.view_layer.objects.active = base

    for obj in list(objects[1:]):
        modifier = base.modifiers.new(name=f"union_{obj.name}", type="BOOLEAN")
        modifier.operation = "UNION"
        modifier.object = obj
        modifier.solver = solver

        bpy.context.view_layer.objects.active = base
        try:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except Exception as exc:
            raise RuntimeError(
                f"Boolean union failed for {obj.name}: {exc}") from exc

        bpy.data.objects.remove(obj, do_unlink=True)

    base.name = "coacd_boolean_union"
    base.data.name = "coacd_boolean_union_mesh"
    return base


def apply_voxel_remesh(obj, voxel_size, adaptivity):
    if voxel_size <= 0:
        raise RuntimeError(f"Voxel size must be positive, got {voxel_size}")

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    modifier = obj.modifiers.new(name="coacd_voxel_remesh", type="REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    modifier.adaptivity = adaptivity
    if hasattr(modifier, "use_remove_disconnected"):
        modifier.use_remove_disconnected = False
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return obj


def triangulate_object(obj):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    modifier = obj.modifiers.new(
        name="triangulate_for_stl", type="TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def export_stl(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if hasattr(bpy.ops.wm, "stl_export"):
        try:
            bpy.ops.wm.stl_export(
                filepath=str(path),
                export_selected_objects=True,
                ascii_format=False,
            )
            return
        except TypeError:
            bpy.ops.wm.stl_export(filepath=str(
                path), export_selected_objects=True)
            return

    try:
        bpy.ops.export_mesh.stl(filepath=str(
            path), use_selection=True, ascii=False)
    except TypeError:
        bpy.ops.export_mesh.stl(filepath=str(path), use_selection=True)


def main():
    args = parse_args()
    input_meshes = [path.resolve() for path in args.input_meshes]
    output_stl = args.output_stl.resolve()

    for input_mesh in input_meshes:
        if not input_mesh.is_file():
            raise SystemExit(f"Input mesh does not exist: {input_mesh}")
        if input_mesh.suffix.lower() not in SUPPORTED_INPUTS:
            raise SystemExit(
                f"Unsupported input mesh format: {input_mesh.suffix}")

    clear_scene()
    for input_mesh in input_meshes:
        import_mesh(input_mesh)

    objects = mesh_objects()
    if args.boolean_union:
        result = boolean_union_objects(objects, args.boolean_solver)
    else:
        result = join_mesh_objects(objects, "coacd_joined_hulls")

    clean_mesh_object(result)

    if args.voxel_remesh:
        result = apply_voxel_remesh(result, args.voxel_size, args.adaptivity)
        clean_mesh_object(result)

    if args.smooth_normals:
        bpy.ops.object.shade_smooth()

    triangulate_object(result)
    export_stl(result, output_stl)

    print(f"[INFO] Input meshes: {len(input_meshes)}")
    print(f"[INFO] Source mesh objects: {len(objects)}")
    print(f"[INFO] Boolean union: {args.boolean_union}")
    print(f"[INFO] Voxel remesh: {args.voxel_remesh}")
    print(f"[INFO] Voxel size: {args.voxel_size}")
    print(f"[INFO] Output STL: {output_stl}")


if __name__ == "__main__":
    main()
