import argparse
import copy
import math
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


PACKAGE_PREFIX = "package://"

COLOR_PALETTE = (
    ("dark_gray", (0.470588, 0.470588, 0.470588, 1.0)),
    ("neutral_gray", (0.501961, 0.501961, 0.501961, 1.0)),
    ("medium_gray", (0.533333, 0.533333, 0.533333, 1.0)),
    ("silver", (0.627451, 0.627451, 0.627451, 1.0)),
    ("warm_white", (1.0, 0.949020, 0.909804, 1.0)),
    ("pale_blue", (0.866667, 0.909804, 1.0, 1.0)),
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Create a MuJoCo-friendly URDF from an existing URDF. Visual DAE "
            "meshes are replaced with color-split OBJ visuals using the "
            "*_mujoco_preview.xml files produced by visual_mesh_merge_and_cluster.py."
        )
    )
    parser.add_argument("input_urdf", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help=(
            "Self-contained output folder. The generated .mujoco.urdf and all "
            "referenced mesh files are copied here."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root. Default: inferred from this script location.",
    )
    parser.add_argument(
        "--package-name",
        default="openarm_description",
        help="ROS package name used in package:// mesh URIs.",
    )
    parser.add_argument(
        "--mesh-path-mode",
        choices=("relative", "absolute", "package"),
        default="relative",
        help=(
            "How mesh filenames are written in the generated URDF. "
            "relative is usually easiest for MuJoCo."
        ),
    )
    parser.add_argument(
        "--material-prefix",
        default="openarm",
        help="Prefix for generated global material names.",
    )
    parser.add_argument(
        "--mujoco-meshdir",
        default="meshes",
        help=(
            "Value written to <mujoco><compiler meshdir=...>. Bundled mesh "
            "filenames are written relative to this directory."
        ),
    )
    parser.add_argument(
        "--mujoco-texturedir",
        default=None,
        help="Optional value written to <mujoco><compiler texturedir=...>.",
    )
    parser.add_argument(
        "--visual-mesh-root",
        default="visual",
        help="Subdirectory under meshdir used for visual meshes.",
    )
    parser.add_argument(
        "--collision-mesh-root",
        default="collision",
        help="Subdirectory under meshdir used for collision meshes.",
    )
    parser.add_argument(
        "--split-collision-meshes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Replace a collision STL with multiple STL collisions when "
            "<stl-parent>/splited/<stl-stem>/ contains STL parts."
        ),
    )
    parser.add_argument(
        "--collision-split-dir-name",
        default="splited",
        help="Directory name under a collision STL parent that stores split STL folders.",
    )
    parser.add_argument(
        "--mujoco-basename-aliases",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Also copy mesh files to the meshdir root by basename. MuJoCo's "
            "URDF importer currently strips mesh subdirectories. This is off "
            "by default because convert_mujoco_urdf_to_xml.py creates temporary "
            "aliases during conversion."
        ),
    )
    return parser.parse_args()


def rgba_key(rgba):
    return tuple(round(component, 6) for component in rgba)


def parse_rgba(value):
    parts = [float(part) for part in value.split()]
    if len(parts) != 4:
        raise ValueError(f"Expected four rgba components, got: {value!r}")
    return tuple(parts)


def nearest_color_name(rgba):
    best_name = None
    best_distance = math.inf

    for name, reference in COLOR_PALETTE:
        distance = sum((rgba[index] - reference[index]) ** 2 for index in range(4))
        if distance < best_distance:
            best_name = name
            best_distance = distance

    return best_name or "material"


def sanitize_name(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "material"


def package_uri_to_path(uri, repo_root, package_name):
    package_head = f"{PACKAGE_PREFIX}{package_name}/"
    if not uri.startswith(package_head):
        return None
    return repo_root / uri[len(package_head):]


def rewrite_mesh_filename(filename, repo_root, output_urdf, package_name, mode):
    if mode == "package":
        return filename

    source_path = package_uri_to_path(filename, repo_root, package_name)
    if source_path is None:
        source_path = Path(filename)
        if not source_path.is_absolute():
            source_path = (output_urdf.parent / source_path).resolve()

    if mode == "absolute":
        return str(source_path.resolve())

    return os.path.relpath(source_path.resolve(), output_urdf.parent.resolve())


def resolve_mesh_filename(filename, base_dir, repo_root, package_name):
    source_path = package_uri_to_path(filename, repo_root, package_name)
    if source_path is not None:
        return source_path.resolve()

    path = Path(filename)
    if path.is_absolute():
        return path.resolve()

    return (base_dir / path).resolve()


def path_to_mesh_filename(path, repo_root, output_urdf, package_name, mode):
    path = path.resolve()

    if mode == "absolute":
        return str(path)

    if mode == "package":
        try:
            rel_repo = path.relative_to(repo_root.resolve())
            return f"{PACKAGE_PREFIX}{package_name}/{rel_repo.as_posix()}"
        except ValueError:
            return str(path)

    return os.path.relpath(path, output_urdf.parent.resolve())


def preview_path_for_visual_mesh(filename, repo_root, package_name):
    mesh_path = package_uri_to_path(filename, repo_root, package_name)
    if mesh_path is None:
        mesh_path = Path(filename)

    stem = mesh_path.stem
    candidates = []
    if mesh_path.parent.name == "visual":
        candidates.append(mesh_path.parent / "obj" / f"{stem}_obj")
    candidates.append(mesh_path.parent.parent / "obj" / f"{stem}_obj")

    seen = set()
    for obj_dir in candidates:
        obj_dir = obj_dir.resolve()
        if obj_dir in seen:
            continue
        seen.add(obj_dir)
        preview = obj_dir / f"{stem}_obj_mujoco_preview.xml"
        if preview.is_file():
            return stem, obj_dir, preview

    return stem, candidates[0].resolve(), None


def parse_preview(preview_path):
    tree = ET.parse(preview_path)
    root = tree.getroot()
    asset = root.find("asset")

    if asset is None:
        raise ValueError(f"Missing <asset> in {preview_path}")

    mesh_files = {}
    material_rgba = {}

    for mesh in asset.findall("mesh"):
        name = mesh.get("name")
        file_name = mesh.get("file")
        if name and file_name:
            mesh_files[name] = file_name

    for material in asset.findall("material"):
        name = material.get("name")
        rgba = material.get("rgba")
        if name and rgba:
            material_rgba[name] = parse_rgba(rgba)

    geoms = []
    for geom in root.findall(".//geom"):
        mesh_name = geom.get("mesh")
        material_name = geom.get("material")
        if mesh_name not in mesh_files:
            continue
        if material_name not in material_rgba:
            continue

        geoms.append(
            {
                "mesh_name": mesh_name,
                "file": mesh_files[mesh_name],
                "rgba": material_rgba[material_name],
            }
        )

    if not geoms:
        raise ValueError(f"No mesh/material geom entries found in {preview_path}")

    return geoms


def make_origin_like(visual):
    origin = visual.find("origin")
    if origin is not None:
        return copy.deepcopy(origin)

    return ET.Element("origin", {"rpy": "0 0 0", "xyz": "0 0 0"})


def get_visual_mesh(visual):
    geometry = visual.find("geometry")
    if geometry is None:
        return None
    return geometry.find("mesh")


def get_collision_mesh(collision):
    geometry = collision.find("geometry")
    if geometry is None:
        return None
    return geometry.find("mesh")


def split_collision_parts_for_mesh(mesh_path, split_dir_name="splited"):
    if mesh_path.suffix.lower() != ".stl":
        return []

    split_dir = mesh_path.parent / split_dir_name / mesh_path.stem
    if not split_dir.is_dir():
        return []

    return sorted(
        path
        for path in split_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".stl"
    )


def link_side(link_name):
    for side in ("left", "right"):
        prefix = f"openarm_{side}_"
        if link_name.startswith(prefix):
            return side
    return None


def format_index(index):
    return f"{index:02d}"


def make_visual_name(mesh_stem, link_name, index):
    stem = sanitize_name(mesh_stem)
    formatted_index = format_index(index)
    side = link_side(link_name)
    if side:
        return f"{stem}_{side}_{formatted_index}"
    return f"{stem}_{formatted_index}"


def make_visual_mesh_name(mesh_stem, index):
    return f"{sanitize_name(mesh_stem)}_{format_index(index)}"


def make_unsplit_visual_name(mesh_stem, link_name):
    side = link_side(link_name)
    if side:
        return make_visual_name(mesh_stem, link_name, 0)
    return sanitize_name(mesh_stem)


def make_collision_name(mesh_stem, link_name, index):
    stem = sanitize_name(mesh_stem)
    formatted_index = format_index(index)
    side = link_side(link_name)
    if side:
        return f"{stem}_{side}_collision_{formatted_index}"
    return f"{stem}_collision_{formatted_index}"


def make_collision_mesh_name(mesh_stem, index):
    return f"{sanitize_name(mesh_stem)}_collision_{format_index(index)}"


def make_collision_file_name(mesh_stem, index, include_index):
    stem = sanitize_name(mesh_stem)
    if include_index:
        return f"{stem}_part_{format_index(index)}"
    return stem


def has_compact_collision_name(name):
    if not name:
        return False
    return re.match(r"^[a-z0-9_]+(?:_left|_right)?_collision_[0-9]+$", name) is not None


def split_collision_meshes(robot, args):
    if not args.split_collision_meshes:
        return []

    repo_root = args.repo_root.resolve()
    output_urdf = args.output_urdf.resolve()
    split_entries = []

    for link in robot.findall("link"):
        link_name = link.get("name", "link")
        original_collisions = link.findall("collision")

        for collision in original_collisions:
            mesh = get_collision_mesh(collision)
            filename = mesh.get("filename") if mesh is not None else None
            if not filename:
                continue

            mesh_path = resolve_input_mesh_path(
                filename,
                args.input_urdf.parent,
                repo_root,
                args.package_name,
            )
            parts = split_collision_parts_for_mesh(mesh_path, args.collision_split_dir_name)
            if not parts:
                continue

            insert_index = list(link).index(collision)
            link.remove(collision)

            for index, part_path in enumerate(parts):
                split_collision = copy.deepcopy(collision)
                split_collision.set(
                    "name",
                    make_collision_name(mesh_path.stem, link_name, index),
                )
                split_collision.set(
                    "mujoco_mesh_name",
                    make_collision_mesh_name(mesh_path.stem, index),
                )
                split_collision.set(
                    "mujoco_file_name",
                    make_collision_file_name(mesh_path.stem, index, include_index=True),
                )
                split_mesh = get_collision_mesh(split_collision)
                split_mesh.set(
                    "filename",
                    path_to_mesh_filename(
                        part_path,
                        repo_root,
                        output_urdf,
                        args.package_name,
                        args.mesh_path_mode,
                    ),
                )
                link.insert(insert_index + index, split_collision)

            split_entries.append((link_name, str(mesh_path), len(parts)))

    return split_entries


def normalize_collision_names(robot):
    renamed = []

    for link in robot.findall("link"):
        link_name = link.get("name", "link")
        counters = {}
        stem_counts = {}

        for collision in link.findall("collision"):
            if has_compact_collision_name(collision.get("name")):
                continue

            mesh = get_collision_mesh(collision)
            filename = mesh.get("filename") if mesh is not None else None
            if not filename:
                continue

            stem = sanitize_name(Path(filename).stem)
            stem_counts[stem] = stem_counts.get(stem, 0) + 1

        for collision in link.findall("collision"):
            if has_compact_collision_name(collision.get("name")):
                continue

            mesh = get_collision_mesh(collision)
            filename = mesh.get("filename") if mesh is not None else None
            if not filename:
                continue

            stem = Path(filename).stem
            key = sanitize_name(stem)
            index = counters.get(key, 0)
            counters[key] = index + 1

            old_name = collision.get("name")
            new_name = make_collision_name(stem, link_name, index)
            collision.set("name", new_name)
            collision.set("mujoco_mesh_name", make_collision_mesh_name(stem, index))
            collision.set(
                "mujoco_file_name",
                make_collision_file_name(stem, index, include_index=stem_counts[key] > 1),
            )
            renamed.append((link_name, old_name, new_name))

    return renamed


def resolve_input_mesh_path(filename, base_dir, repo_root, package_name):
    return resolve_mesh_filename(filename, base_dir, repo_root, package_name)


def dae_visual_stl_fallback(filename, link, base_dir, repo_root, package_name):
    if Path(filename).suffix.lower() != ".dae":
        return None

    visual_path = resolve_input_mesh_path(filename, base_dir, repo_root, package_name)
    same_stem_stl = visual_path.with_suffix(".stl")
    if same_stem_stl.is_file():
        return same_stem_stl

    for collision in link.findall("collision"):
        collision_mesh = get_collision_mesh(collision)
        collision_filename = collision_mesh.get("filename") if collision_mesh is not None else None
        if not collision_filename:
            continue

        collision_path = resolve_input_mesh_path(
            collision_filename,
            base_dir,
            repo_root,
            package_name,
        )
        if collision_path.suffix.lower() == ".stl" and collision_path.is_file():
            return collision_path

    return None


def make_split_visual(name, mesh_name, origin, obj_file, scale, material_name):
    visual = ET.Element("visual", {"name": name, "mujoco_mesh_name": mesh_name})
    visual.append(copy.deepcopy(origin))

    geometry = ET.SubElement(visual, "geometry")
    mesh_attrs = {"filename": obj_file}
    if scale:
        mesh_attrs["scale"] = scale
    ET.SubElement(geometry, "mesh", mesh_attrs)
    ET.SubElement(visual, "material", {"name": material_name})
    return visual


def collect_existing_global_materials(robot):
    return [child for child in robot if child.tag == "material"]


def remove_generated_materials(robot, prefix):
    for child in list(robot):
        if child.tag == "material" and child.get("name", "").startswith(prefix + "_"):
            robot.remove(child)


def insert_global_materials(robot, material_names_by_rgba):
    insert_at = 0
    while insert_at < len(robot) and robot[insert_at].tag == "material":
        insert_at += 1

    for rgba, material_name in sorted(material_names_by_rgba.items(), key=lambda item: item[1]):
        material = ET.Element("material", {"name": material_name})
        ET.SubElement(material, "color", {"rgba": " ".join(f"{value:.6f}" for value in rgba)})
        robot.insert(insert_at, material)
        insert_at += 1


def material_name_for_rgba(rgba, used_names, rgba_to_name, prefix):
    key = rgba_key(rgba)
    if key in rgba_to_name:
        return rgba_to_name[key]

    base = sanitize_name(f"{prefix}_{nearest_color_name(rgba)}")
    name = base
    suffix = 2
    while name in used_names:
        name = f"{base}_{suffix}"
        suffix += 1

    used_names.add(name)
    rgba_to_name[key] = name
    return name


def rewrite_all_mesh_paths(robot, repo_root, output_urdf, package_name, mode):
    for mesh in robot.findall(".//mesh"):
        filename = mesh.get("filename")
        if filename:
            mesh.set(
                "filename",
                rewrite_mesh_filename(filename, repo_root, output_urdf, package_name, mode),
            )


def replace_visuals(robot, args):
    repo_root = args.repo_root.resolve()
    output_urdf = args.output_urdf.resolve()
    used_material_names = {
        material.get("name")
        for material in collect_existing_global_materials(robot)
        if material.get("name")
    }
    rgba_to_name = {}
    material_names_by_rgba = {}
    replaced = []
    kept = []
    dae_stl_fallbacks = []

    for link in robot.findall("link"):
        link_name = link.get("name", "")
        original_visuals = link.findall("visual")
        new_visuals = []
        visual_insert_index = None

        for visual in original_visuals:
            if visual_insert_index is None:
                visual_insert_index = list(link).index(visual)

            mesh = get_visual_mesh(visual)
            filename = mesh.get("filename") if mesh is not None else None
            if not filename:
                new_visuals.append(copy.deepcopy(visual))
                continue

            stem, obj_dir, preview = preview_path_for_visual_mesh(
                filename,
                repo_root,
                args.package_name,
            )
            if preview is None:
                copied = copy.deepcopy(visual)
                copied.set("name", make_unsplit_visual_name(stem, link_name))
                copied_mesh = get_visual_mesh(copied)
                if copied_mesh is not None:
                    fallback_stl = dae_visual_stl_fallback(
                        filename,
                        link,
                        args.input_urdf.parent,
                        repo_root,
                        args.package_name,
                    )
                    output_filename = filename
                    reason = "missing split preview"
                    if fallback_stl is not None:
                        output_filename = path_to_mesh_filename(
                            fallback_stl,
                            repo_root,
                            output_urdf,
                            args.package_name,
                            args.mesh_path_mode,
                        )
                        reason = "missing split preview, using STL fallback"
                        dae_stl_fallbacks.append((link_name, filename, str(fallback_stl)))

                    copied_mesh.set(
                        "filename",
                        rewrite_mesh_filename(
                            output_filename,
                            repo_root,
                            output_urdf,
                            args.package_name,
                            args.mesh_path_mode,
                        ),
                    )
                new_visuals.append(copied)
                kept.append((link_name, stem, reason))
                continue

            origin = make_origin_like(visual)
            scale = mesh.get("scale")
            geoms = parse_preview(preview)

            for index, geom in enumerate(geoms):
                rgba = rgba_key(geom["rgba"])
                material_name = material_name_for_rgba(
                    rgba,
                    used_material_names,
                    rgba_to_name,
                    args.material_prefix,
                )
                material_names_by_rgba[rgba] = material_name
                obj_file = path_to_mesh_filename(
                    obj_dir / geom["file"],
                    repo_root,
                    output_urdf,
                    args.package_name,
                    args.mesh_path_mode,
                )
                new_visuals.append(
                    make_split_visual(
                        make_visual_name(stem, link_name, index),
                        make_visual_mesh_name(stem, index),
                        origin,
                        obj_file,
                        scale,
                        material_name,
                    )
                )

            replaced.append((link_name, stem, len(geoms)))

        for visual in original_visuals:
            link.remove(visual)

        if visual_insert_index is None:
            continue

        for offset, visual in enumerate(new_visuals):
            link.insert(visual_insert_index + offset, visual)

    return material_names_by_rgba, replaced, kept, dae_stl_fallbacks


def strip_ros_only_tags(robot):
    for tag in ("gazebo", "transmission", "ros2_control"):
        for child in list(robot):
            if child.tag == tag:
                robot.remove(child)


def ensure_mujoco_compiler(robot, meshdir=None, texturedir=None):
    mujoco = robot.find("mujoco")
    if mujoco is None:
        mujoco = ET.Element("mujoco")
        robot.insert(0, mujoco)

    compiler = mujoco.find("compiler")
    if compiler is None:
        compiler = ET.SubElement(mujoco, "compiler")

    compiler.set("discardvisual", "false")
    if meshdir:
        compiler.set("meshdir", meshdir)
    else:
        compiler.attrib.pop("meshdir", None)

    if texturedir:
        compiler.set("texturedir", texturedir)
    else:
        compiler.attrib.pop("texturedir", None)


def write_xml(tree, output_path):
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def build_parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


def containing_mesh_block(mesh, parent_map):
    current = parent_map.get(mesh)
    while current is not None:
        if current.tag in ("visual", "collision"):
            return current.tag, current
        current = parent_map.get(current)
    return "visual", None


def mesh_destination_root(role, args):
    root = args.collision_mesh_root if role == "collision" else args.visual_mesh_root
    return Path(root)


def destination_name_for_mesh(source_path, role, block, args):
    if block is not None and block.tag in ("visual", "collision"):
        explicit_name = block.get("mujoco_file_name")
        if explicit_name:
            block_name = sanitize_name(explicit_name)
            if block_name:
                return f"{block_name}{source_path.suffix.lower()}"

    return source_path.name


def unique_mesh_path(source_path, meshdir, role, bundle_dir, used_destinations, args, destination_name=None):
    destination = bundle_dir / meshdir / mesh_destination_root(role, args) / (
        destination_name or source_path.name
    )
    relative_destination = destination.relative_to(bundle_dir)
    key = relative_destination.as_posix()
    if key not in used_destinations:
        used_destinations[key] = source_path.resolve()
        return destination

    if used_destinations[key] == source_path.resolve():
        return destination

    for index in range(1, 10000):
        candidate = destination.with_name(f"{source_path.stem}_{index:03d}{source_path.suffix}")
        candidate_key = candidate.relative_to(bundle_dir).as_posix()
        if candidate_key not in used_destinations:
            used_destinations[candidate_key] = source_path.resolve()
            return candidate

    raise RuntimeError(f"Could not create unique mesh name for {source_path}")


def basename_alias_path(source_path, meshdir, bundle_dir, used_aliases, alias_name=None):
    destination = bundle_dir / meshdir / (alias_name or source_path.name)
    key = destination.name
    if key not in used_aliases:
        used_aliases[key] = source_path.resolve()
        return destination

    if used_aliases[key] == source_path.resolve():
        return destination

    raise RuntimeError(
        "MuJoCo URDF importer strips mesh directories, so basename aliases "
        f"must be unique. Conflicting mesh basename: {source_path.name}"
    )


def copy_mesh_with_sidecars(source_path, destination):
    if not source_path.is_file():
        raise FileNotFoundError(f"Referenced mesh does not exist: {source_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != destination.resolve():
        shutil.copy2(source_path, destination)

    copied = [destination]
    if source_path.suffix.lower() == ".obj":
        mtl_path = source_path.with_suffix(".mtl")
        if mtl_path.is_file():
            mtl_destination = destination.with_suffix(".mtl")
            if mtl_path.resolve() != mtl_destination.resolve():
                shutil.copy2(mtl_path, mtl_destination)
            copied.append(mtl_destination)

    return copied


def write_bundle(source_urdf, bundle_dir, repo_root, package_name, args):
    bundle_dir = bundle_dir.resolve()
    bundle_urdf = bundle_dir / source_urdf.name
    meshdir = Path(args.mujoco_meshdir)
    if meshdir.is_absolute():
        raise ValueError("--mujoco-meshdir must be relative for a portable bundle")

    tree = ET.parse(source_urdf)
    robot = tree.getroot()
    parent_map = build_parent_map(robot)
    copied_meshes = {}
    used_destinations = {}
    used_aliases = {}

    for mesh in robot.findall(".//mesh"):
        filename = mesh.get("filename")
        if not filename:
            continue

        source_path = resolve_mesh_filename(
            filename,
            source_urdf.parent,
            repo_root,
            package_name,
        )
        role, block = containing_mesh_block(mesh, parent_map)
        destination_name = destination_name_for_mesh(source_path, role, block, args)
        destination = unique_mesh_path(
            source_path,
            meshdir,
            role,
            bundle_dir,
            used_destinations,
            args,
            destination_name,
        )
        copied = copy_mesh_with_sidecars(source_path, destination)
        if args.mujoco_basename_aliases:
            alias = basename_alias_path(
                source_path,
                meshdir,
                bundle_dir,
                used_aliases,
                destination.name,
            )
            copied.extend(copy_mesh_with_sidecars(source_path, alias))
        copied_meshes[str(source_path)] = copied
        mesh.set("filename", destination.relative_to(bundle_dir / meshdir).as_posix())

    for block in robot.findall(".//visual") + robot.findall(".//collision"):
        block.attrib.pop("mujoco_mesh_name", None)
        block.attrib.pop("mujoco_file_name", None)

    ensure_mujoco_compiler(robot, args.mujoco_meshdir, args.mujoco_texturedir)

    write_xml(tree, bundle_urdf)
    return bundle_urdf, copied_meshes


def resolve_output_paths(args):
    output_dir = args.output_dir.resolve()
    output_urdf = output_dir / f"{args.input_urdf.stem}.mujoco.urdf"
    return output_urdf, output_dir


def main():
    args = parse_args()
    args.input_urdf = args.input_urdf.resolve()
    args.repo_root = args.repo_root.resolve()
    args.output_urdf, output_dir = resolve_output_paths(args)

    tree = ET.parse(args.input_urdf)
    robot = tree.getroot()

    strip_ros_only_tags(robot)
    ensure_mujoco_compiler(robot, args.mujoco_meshdir, args.mujoco_texturedir)
    remove_generated_materials(robot, args.material_prefix)
    material_names_by_rgba, replaced, kept, dae_stl_fallbacks = replace_visuals(robot, args)
    split_collisions = split_collision_meshes(robot, args)
    renamed_collisions = normalize_collision_names(robot)
    insert_global_materials(robot, material_names_by_rgba)
    rewrite_all_mesh_paths(
        robot,
        args.repo_root,
        args.output_urdf,
        args.package_name,
        args.mesh_path_mode,
    )
    write_xml(tree, args.output_urdf)

    bundle_urdf, copied_meshes = write_bundle(
        args.output_urdf,
        output_dir,
        args.repo_root,
        args.package_name,
        args,
    )
    print(f"Wrote {bundle_urdf}")
    print(f"Bundled mesh files: {sum(len(paths) for paths in copied_meshes.values())}")

    print(f"Replaced visual links: {len(replaced)}")
    for link_name, stem, count in replaced:
        print(f"  {link_name}: {stem} -> {count} OBJ visuals")

    if kept:
        print(f"Kept unsplit visuals: {len(kept)}")
        for link_name, stem, reason in kept:
            print(f"  {link_name}: {stem} ({reason})")

    if dae_stl_fallbacks:
        print(f"DAE visual STL fallbacks: {len(dae_stl_fallbacks)}")
        for link_name, original, fallback in dae_stl_fallbacks:
            print(f"  {link_name}: {original} -> {fallback}")

    if split_collisions:
        print(f"Split collision meshes: {len(split_collisions)}")
        for link_name, original, count in split_collisions:
            print(f"  {link_name}: {original} -> {count} STL collisions")

    if renamed_collisions:
        print(f"Renamed collision geoms: {len(renamed_collisions)}")
        for link_name, old_name, new_name in renamed_collisions:
            old_text = old_name or "(unnamed)"
            print(f"  {link_name}: {old_text} -> {new_name}")

    if material_names_by_rgba:
        print("Materials:")
        for rgba, name in sorted(material_names_by_rgba.items(), key=lambda item: item[1]):
            print(f"  {name}: {' '.join(f'{value:.6f}' for value in rgba)}")


if __name__ == "__main__":
    main()
