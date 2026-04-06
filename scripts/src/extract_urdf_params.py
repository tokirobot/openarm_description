#!/usr/bin/env python3
"""Extract robot parameters from a URDF into YAML config files.

This script is intended to support the pipeline:

  arbitrary URDF -> YAML parameter files -> xacro assembly or downstream tools

It reads link/joint data from a URDF and writes:

  - topology.yaml
  - joint_origins.yaml
  - joint_axes.yaml
  - joint_limits.yaml
  - joint_mimics.yaml
  - inertials/nominal.yaml
  - visuals.yaml
  - collisions.yaml

The output format is designed to become the long-term parameter source that
assembly xacros consume.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract topology, kinematics, limits, inertials, and mesh data from a URDF."
    )
    parser.add_argument(
        "--urdf",
        required=True,
        help="Path to the source URDF file.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help=(
            "Output root directory. Writes directly into this path, or into "
            "<output-dir>/<output-folder> when --output-folder is set."
        ),
    )
    parser.add_argument(
        "--output-folder",
        default="",
        help=(
            "Optional subdirectory name under --output-dir. "
            "If omitted, files are written directly under --output-dir."
        ),
    )
    parser.add_argument(
        "--configs-layout",
        choices=["tree", "flat"],
        default="tree",
        help="Config file layout under the chosen output path. Default: tree.",
    )
    parser.add_argument(
        "--inertials-name",
        default="nominal",
        help="Filename stem for inertials output under inertials/. Default: nominal.",
    )
    parser.add_argument(
        "--content",
        choices=["all", "inertials"],
        default="all",
        help="Which content to export. Default: all.",
    )
    parser.add_argument(
        "--mesh-prefix",
        default="",
        help=(
            "Optional mesh path prefix. Visual meshes are rewritten under "
            "<mesh-prefix>/visual and collision meshes under <mesh-prefix>/collision."
        ),
    )
    parser.add_argument(
        "--mesh-copy-to",
        default="",
        help=(
            "Filesystem destination root for copied meshes. Visual meshes are copied to "
            "<mesh-copy-to>/visual and collision meshes to <mesh-copy-to>/collision."
        ),
    )
    parser.add_argument(
        "--existing-config",
        choices=["prompt", "overwrite", "skip"],
        default="prompt",
        help="Conflict policy for existing config YAML files. Default: prompt.",
    )
    parser.add_argument(
        "--existing-mesh",
        choices=["prompt", "overwrite", "skip"],
        default="prompt",
        help="Conflict policy for existing mesh files. Default: prompt.",
    )
    parser.add_argument(
        "--existing-inertials",
        choices=["prompt", "overwrite", "skip", "number"],
        default="prompt",
        help="Conflict policy for existing inertials YAML files. Default: prompt.",
    )
    parser.add_argument(
        "--include-links",
        default="",
        help="Comma-separated link names to keep. Default: all links.",
    )
    parser.add_argument(
        "--exclude-links",
        default="",
        help="Comma-separated link names to skip after inclusion filtering.",
    )
    parser.add_argument(
        "--include-joints",
        default="",
        help="Comma-separated joint names to keep. Default: all joints.",
    )
    parser.add_argument(
        "--exclude-joints",
        default="",
        help="Comma-separated joint names to skip after inclusion filtering.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indent width for generated YAML. Default: 2.",
    )
    parser.add_argument(
        "--root-link",
        default="",
        help="Optional root link for traversal. Default: infer from filtered joints.",
    )
    parser.add_argument(
        "--truncate-at-joint",
        default="",
        help="Optional joint name used as the split boundary.",
    )
    parser.add_argument(
        "--split-reference-mode",
        choices=["create_virtual", "use_joint"],
        default="create_virtual",
        help=(
            "How to describe the split boundary when --save-subtree is enabled. "
            "'create_virtual' keeps the selected split joint in the primary topology and "
            "creates a virtual fixed boundary on the split joint child frame. "
            "'use_joint' treats the split joint itself as the reference point and requires a fixed joint."
        ),
    )
    parser.add_argument(
        "--save-subtree",
        action="store_true",
        help=(
            "When used with --truncate-at-joint, also export the subtree after that "
            "joint as a separate YAML set."
        ),
    )
    parser.add_argument(
        "--subtree-output-dir",
        default="",
        help=(
            "Output root directory for the truncated subtree. "
            "If omitted, defaults to <primary-output>_subtree."
        ),
    )
    parser.add_argument(
        "--subtree-output-folder",
        default="",
        help="Optional subdirectory name under --subtree-output-dir.",
    )
    parser.add_argument(
        "--subtree-configs-layout",
        choices=["tree", "flat"],
        default="tree",
        help="Config file layout for the truncated subtree. Default: tree.",
    )
    parser.add_argument(
        "--subtree-inertials-name",
        default="nominal",
        help="Filename stem for subtree inertials output under inertials/. Default: nominal.",
    )
    parser.add_argument(
        "--subtree-content",
        choices=["all", "inertials"],
        default="all",
        help="Which content to export for the subtree. Default: all.",
    )
    parser.add_argument(
        "--subtree-mesh-prefix",
        default="",
        help=(
            "Optional mesh path prefix for the truncated subtree. Visual meshes are rewritten under "
            "<subtree-mesh-prefix>/visual and collision meshes under <subtree-mesh-prefix>/collision."
        ),
    )
    parser.add_argument(
        "--subtree-mesh-copy-to",
        default="",
        help=(
            "Filesystem destination root for copied subtree meshes. Visual meshes are copied to "
            "<subtree-mesh-copy-to>/visual and collision meshes to <subtree-mesh-copy-to>/collision."
        ),
    )
    return parser.parse_args()


@dataclass(frozen=True)
class ExportSpec:
    configs_layout: str
    output_dir: str
    output_folder: str
    inertials_name: str
    content: str
    mesh_prefix: str
    mesh_copy_to: str
    existing_config: str
    existing_mesh: str
    existing_inertials: str


def csv_arg(value: str) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_xyz_attr(text: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not text:
        return default
    parts = text.split()
    if len(parts) != 3:
        raise ValueError(f"Expected 3 values, got {text!r}")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def ordered_xyz(x: float, y: float, z: float) -> OrderedDict:
    return OrderedDict([("x", x), ("y", y), ("z", z)])


def ordered_origin(xyz: tuple[float, float, float], rpy: tuple[float, float, float]) -> OrderedDict:
    return OrderedDict(
        [
            ("x", xyz[0]),
            ("y", xyz[1]),
            ("z", xyz[2]),
            ("roll", rpy[0]),
            ("pitch", rpy[1]),
            ("yaw", rpy[2]),
        ]
    )


def parse_origin(element: ET.Element | None) -> OrderedDict:
    xyz = parse_xyz_attr(element.get(
        "xyz") if element is not None else None, (0.0, 0.0, 0.0))
    rpy = parse_xyz_attr(element.get(
        "rpy") if element is not None else None, (0.0, 0.0, 0.0))
    return ordered_origin(xyz, rpy)


def parse_scale_attr(text: str | None) -> OrderedDict:
    xyz = parse_xyz_attr(text, (1.0, 1.0, 1.0))
    return ordered_xyz(xyz[0], xyz[1], xyz[2])


def maybe_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def normalize_reference_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_",
                        value.strip().lower()).strip("_")
    return normalized or "reference_point"


def should_keep(name: str, include: set[str], exclude: set[str]) -> bool:
    if include and name not in include:
        return False
    if name in exclude:
        return False
    return True


def filter_joint_by_links(joint_parent: str, joint_child: str, link_include: set[str], link_exclude: set[str]) -> bool:
    if link_include and (joint_parent not in link_include or joint_child not in link_include):
        return False
    if joint_parent in link_exclude or joint_child in link_exclude:
        return False
    return True


def yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isfinite(value):
            return format(value, ".16g")
        raise ValueError(f"Cannot serialize non-finite float: {value}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if value == "" or any(ch in value for ch in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", "\""]) or value.strip() != value:
            escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
            return f"\"{escaped}\""
        return value
    raise TypeError(f"Unsupported YAML scalar type: {type(value)!r}")


def dump_yaml(data: object, indent: int = 2, level: int = 0) -> str:
    pad = " " * (indent * level)
    if isinstance(data, (dict, OrderedDict)):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, OrderedDict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(dump_yaml(value, indent=indent, level=level + 1))
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, OrderedDict)):
                lines.append(f"{pad}-")
                lines.append(dump_yaml(item, indent=indent, level=level + 1))
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(dump_yaml(item, indent=indent, level=level + 1))
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{yaml_scalar(data)}"


def write_yaml(path: Path, data: object, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data, indent=indent) + "\n", encoding="utf-8")


def prompt_choice(prompt: str, choices: dict[str, str]) -> str:
    while True:
        answer = input(f"{prompt} [{' / '.join(choices)}]: ").strip().lower()
        if answer in choices:
            return choices[answer]
        print(f"Please choose one of: {', '.join(choices)}")


def next_numbered_path(path: Path) -> Path:
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def resolve_existing_path(path: Path, policy: str, label: str) -> Path | None:
    if not path.exists():
        return path

    action = policy
    if policy == "prompt":
        action = prompt_choice(
            f"{label} already exists at {path}. Choose action",
            {
                "overwrite": "overwrite",
                "skip": "skip",
                "number": "number",
            },
        )

    if action == "overwrite":
        print(f"[overwrite] {label}: {path}")
        return path
    if action == "skip":
        print(f"[skip] {label}: {path}")
        return None
    if action == "number":
        numbered = next_numbered_path(path)
        print(f"[number] {label}: {path} -> {numbered}")
        return numbered

    raise ValueError(f"Unsupported existing-path policy: {policy}")


def resolve_existing_path_without_number(path: Path, policy: str, label: str) -> Path | None:
    if not path.exists():
        return path

    action = policy
    if policy == "prompt":
        action = prompt_choice(
            f"{label} already exists at {path}. Choose action",
            {
                "overwrite": "overwrite",
                "skip": "skip",
            },
        )

    if action == "overwrite":
        print(f"[overwrite] {label}: {path}")
        return path
    if action == "skip":
        print(f"[skip] {label}: {path}")
        return None

    raise ValueError(f"Unsupported existing-path policy: {policy}")


def extract_geometry(section: ET.Element) -> OrderedDict:
    mesh = section.find("geometry/mesh")
    geometry = OrderedDict()
    geometry["mesh"] = mesh.get("filename") if mesh is not None else ""
    geometry["scale"] = parse_scale_attr(
        mesh.get("scale") if mesh is not None else None)
    return geometry


def rewrite_mesh_paths(
    payload: dict[str, object],
    mesh_prefix: str,
) -> None:
    visuals = payload["visuals"]
    collisions = payload["collisions"]

    for _, entry in visuals.items():
        mesh_path = Path(str(entry["geometry"]["mesh"]))
        if mesh_prefix:
            entry["geometry"]["mesh"] = f"{mesh_prefix}/visual/{mesh_path.name}"

    for _, entry in collisions.items():
        mesh_path = Path(str(entry["geometry"]["mesh"]))
        if mesh_prefix:
            entry["geometry"]["mesh"] = f"{mesh_prefix}/collision/{mesh_path.name}"


def resolve_package_path(package_name: str, urdf_path: Path, package_cache: dict[str, Path | None]) -> Path | None:
    if package_name in package_cache:
        return package_cache[package_name]

    for ancestor in [urdf_path.parent, *urdf_path.parents]:
        if ancestor.name == package_name and (ancestor / "package.xml").exists():
            package_cache[package_name] = ancestor
            return ancestor

    for ancestor in [urdf_path.parent, *urdf_path.parents]:
        direct_candidate = ancestor / package_name
        if (direct_candidate / "package.xml").exists():
            package_cache[package_name] = direct_candidate
            return direct_candidate

        src_candidate = ancestor / "src" / package_name
        if (src_candidate / "package.xml").exists():
            package_cache[package_name] = src_candidate
            return src_candidate

    package_cache[package_name] = None
    return None


def resolve_mesh_source(mesh_ref: str, urdf_path: Path, package_cache: dict[str, Path | None]) -> Path | None:
    if not mesh_ref:
        return None

    if mesh_ref.startswith("package://"):
        package_and_rest = mesh_ref[len("package://"):]
        if "/" not in package_and_rest:
            return None
        package_name, relative_path = package_and_rest.split("/", 1)
        package_root = resolve_package_path(
            package_name, urdf_path, package_cache)
        if package_root is None:
            return None
        return (package_root / relative_path).resolve()

    mesh_path = Path(mesh_ref)
    if mesh_path.is_absolute():
        return mesh_path

    return (urdf_path.parent / mesh_path).resolve()


def copy_mesh_entries(
    entries: OrderedDict,
    target_dir: str,
    urdf_path: Path,
    policy: str,
    label: str,
) -> None:
    if not target_dir:
        return

    package_cache: dict[str, Path | None] = {}
    destination_root = Path(target_dir)
    destination_root.mkdir(parents=True, exist_ok=True)
    copied_targets: dict[Path, Path] = {}

    for entry in entries.values():
        mesh_ref = str(entry["geometry"]["mesh"])
        source_path = resolve_mesh_source(mesh_ref, urdf_path, package_cache)
        if source_path is None or not source_path.exists():
            raise FileNotFoundError(
                f"Unable to resolve source mesh '{mesh_ref}' for {label}.")

        candidate_target = destination_root / source_path.name
        target_path = copied_targets.get(candidate_target)
        if target_path is None:
            resolved_target = resolve_existing_path_without_number(
                candidate_target, policy, f"{label} mesh")
            if resolved_target is None:
                continue
            target_path = resolved_target
            copied_targets[candidate_target] = target_path
            if target_path != source_path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)


def copy_meshes_from_payload(payload: dict[str, object], spec: ExportSpec, urdf_path: Path) -> None:
    if not spec.mesh_copy_to:
        return
    copy_mesh_entries(
        payload["visuals"],
        str(Path(spec.mesh_copy_to) / "visual"),
        urdf_path,
        spec.existing_mesh,
        "visual",
    )
    copy_mesh_entries(
        payload["collisions"],
        str(Path(spec.mesh_copy_to) / "collision"),
        urdf_path,
        spec.existing_mesh,
        "collision",
    )


def find_root_link(joints: list[dict[str, object]], requested_root: str) -> str:
    if requested_root:
        return requested_root

    parent_links = {str(joint["parent"]) for joint in joints}
    child_links = {str(joint["child"]) for joint in joints}
    root_candidates = [
        link for link in parent_links if link not in child_links]
    if root_candidates:
        return root_candidates[0]

    raise ValueError(
        "Unable to infer root link from filtered joint set. Pass --root-link explicitly.")


def build_outgoing_joint_map(joints: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    outgoing: dict[str, list[dict[str, object]]] = {}
    for joint in joints:
        outgoing.setdefault(str(joint["parent"]), []).append(joint)
    return outgoing


def build_child_joint_map(joints: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(joint["child"]): joint for joint in joints}


def is_empty_link_record(link_record: dict[str, object]) -> bool:
    return not any(key in link_record for key in ("inertial", "visual", "collision"))


def make_reference_descriptor(
    name: str,
    kind: str,
    source_joint: dict[str, object],
    parent_link: str,
    child_link: str,
    frame_parent_link: str,
    frame_origin: OrderedDict,
) -> OrderedDict:
    descriptor = OrderedDict(
        [
            ("name", name),
            ("kind", kind),
            ("source_joint_name", str(source_joint["name"])),
            ("source_joint_type", str(source_joint["type"])),
            ("parent_link_name", parent_link),
            ("child_link_name", child_link),
            ("frame_parent_link_name", frame_parent_link),
            ("frame_origin", frame_origin),
            ("axis", source_joint["axis"]),
        ]
    )
    if "limit" in source_joint:
        descriptor["limit"] = source_joint["limit"]
    return descriptor


def reference_note_for_kind(kind: str) -> str:
    notes = {
        "joint_definition": "Reference frame derived from a joint definition kept in the exported topology.",
        "grasp_frame": "Detected grasp helper frame derived from a terminal empty-link chain.",
        "assembly_mount": "Detected assembly mount reference derived from a terminal empty-link chain.",
        "reference_point": "Detected generic reference point derived from a terminal empty-link chain.",
    }
    return notes.get(kind, "Reference frame metadata recorded during extraction.")


def ensure_unique_reference_name(name: str, seen_names: set[str]) -> str:
    if name not in seen_names:
        seen_names.add(name)
        return name
    index = 2
    while f"{name}_{index}" in seen_names:
        index += 1
    unique_name = f"{name}_{index}"
    seen_names.add(unique_name)
    return unique_name


def classify_reference_descriptor(
    joint: dict[str, object],
    child_link_name: str,
    keep_in_topology: bool,
    seen_names: set[str],
) -> OrderedDict:
    joint_name = str(joint["name"])
    link_name = child_link_name
    lowered = f"{joint_name} {link_name}".lower()

    if keep_in_topology:
        base_name = f"{normalize_reference_name(joint_name)}_definition_point"
        name = ensure_unique_reference_name(base_name, seen_names)
        kind = "joint_definition"
        frame_parent_link = link_name
        frame_origin = ordered_origin((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return make_reference_descriptor(
            name=name,
            kind=kind,
            source_joint=joint,
            parent_link=str(joint["parent"]),
            child_link=link_name,
            frame_parent_link=frame_parent_link,
            frame_origin=frame_origin,
        )

    if "grasp" in lowered:
        preferred = link_name if "grasp" in link_name.lower() else joint_name
        name = ensure_unique_reference_name(
            normalize_reference_name(preferred), seen_names)
        kind = "grasp_frame"
    elif "mount" in lowered:
        preferred = normalize_reference_name(joint_name)
        if preferred.endswith("_joint"):
            preferred = preferred[:-6]
        if not preferred.endswith("_point"):
            preferred = f"{preferred}_point"
        name = ensure_unique_reference_name(preferred, seen_names)
        kind = "assembly_mount"
    else:
        preferred = normalize_reference_name(link_name)
        if preferred.startswith("empty_link_for_"):
            preferred = normalize_reference_name(joint_name)
        if not preferred.endswith("_point"):
            preferred = f"{preferred}_point"
        name = ensure_unique_reference_name(preferred, seen_names)
        kind = "reference_point"

    return make_reference_descriptor(
        name=name,
        kind=kind,
        source_joint=joint,
        parent_link=str(joint["parent"]),
        child_link=link_name,
        frame_parent_link=str(joint["parent"]),
        frame_origin=joint["origin"],
    )


def detect_terminal_reference_points(
    raw_links: OrderedDict[str, dict[str, object]],
    raw_joints: list[dict[str, object]],
) -> tuple[set[str], set[str], list[OrderedDict]]:
    outgoing_joint_map = build_outgoing_joint_map(raw_joints)
    child_joint_map = build_child_joint_map(raw_joints)
    excluded_links: set[str] = set()
    excluded_joints: set[str] = set()
    reference_descriptors: list[OrderedDict] = []
    seen_reference_names: set[str] = set()

    leaf_links = [
        link_name for link_name in raw_links if link_name not in outgoing_joint_map]

    for leaf_link_name in leaf_links:
        if not is_empty_link_record(raw_links[leaf_link_name]):
            continue

        chain_links: list[str] = []
        chain_joints: list[dict[str, object]] = []
        current_link_name = leaf_link_name

        while True:
            if not is_empty_link_record(raw_links[current_link_name]):
                break
            parent_joint = child_joint_map.get(current_link_name)
            if parent_joint is None:
                break

            chain_links.append(current_link_name)
            chain_joints.append(parent_joint)

            parent_link_name = str(parent_joint["parent"])
            if len(outgoing_joint_map.get(parent_link_name, [])) != 1:
                break
            if not is_empty_link_record(raw_links[parent_link_name]):
                break

            current_link_name = parent_link_name

        chain_links.reverse()
        chain_joints.reverse()

        if not chain_joints:
            continue

        for index, (joint, link_name) in enumerate(zip(chain_joints, chain_links)):
            keep_in_topology = index == 0 and len(
                chain_joints) > 1 and str(joint["type"]) != "fixed"
            if keep_in_topology:
                continue

            descriptor = classify_reference_descriptor(
                joint=joint,
                child_link_name=link_name,
                keep_in_topology=False,
                seen_names=seen_reference_names,
            )
            reference_descriptors.append(descriptor)
            excluded_joints.add(str(joint["name"]))
            excluded_links.add(link_name)

    return excluded_links, excluded_joints, reference_descriptors


def traverse_tree(
    root_link: str,
    outgoing_joint_map: dict[str, list[dict[str, object]]],
    truncate_at_joint: str,
) -> tuple[list[str], list[dict[str, object]]]:
    ordered_links: list[str] = []
    ordered_joints: list[dict[str, object]] = []
    visited_links: set[str] = set()
    visited_joints: set[str] = set()

    def walk(link_name: str) -> None:
        if link_name not in visited_links:
            visited_links.add(link_name)
            ordered_links.append(link_name)

        for joint in outgoing_joint_map.get(link_name, []):
            joint_name = str(joint["name"])
            child_link = str(joint["child"])

            if joint_name in visited_joints:
                continue

            if truncate_at_joint and joint_name == truncate_at_joint:
                continue

            visited_joints.add(joint_name)
            ordered_joints.append(joint)

            if child_link not in visited_links:
                visited_links.add(child_link)
                ordered_links.append(child_link)

            walk(child_link)

    walk(root_link)
    return ordered_links, ordered_joints


def traverse_tree_with_virtual_split(
    root_link: str,
    outgoing_joint_map: dict[str, list[dict[str, object]]],
    truncate_at_joint: str,
) -> tuple[list[str], list[dict[str, object]]]:
    ordered_links: list[str] = []
    ordered_joints: list[dict[str, object]] = []
    visited_links: set[str] = set()
    visited_joints: set[str] = set()

    def walk(link_name: str) -> None:
        if link_name not in visited_links:
            visited_links.add(link_name)
            ordered_links.append(link_name)

        for joint in outgoing_joint_map.get(link_name, []):
            joint_name = str(joint["name"])
            child_link = str(joint["child"])

            if joint_name in visited_joints:
                continue

            visited_joints.add(joint_name)
            ordered_joints.append(joint)

            if child_link not in visited_links:
                visited_links.add(child_link)
                ordered_links.append(child_link)

            if truncate_at_joint and joint_name == truncate_at_joint:
                continue

            walk(child_link)

    walk(root_link)
    return ordered_links, ordered_joints


def canonical_link_name(index: int) -> str:
    if index == 0:
        return "base_link"
    return f"link{index}"


def canonical_joint_name(index: int) -> str:
    return f"joint{index + 1}"


def ordered_mapping(entries: list[tuple[str, str]]) -> OrderedDict:
    return OrderedDict((key, value) for key, value in entries)


def validate_export_spec(spec: ExportSpec, label: str) -> None:
    if not spec.output_dir:
        raise ValueError(f"{label}: --output-dir is required.")


def validate_optional_export_spec(spec: ExportSpec, label: str) -> None:
    if not spec.output_dir:
        return


def resolve_export_dir(spec: ExportSpec, fallback_dir: str = "") -> Path:
    base_dir = Path(spec.output_dir) if spec.output_dir else (
        Path(fallback_dir) if fallback_dir else None)
    if base_dir is None:
        raise ValueError("No output destination configured.")
    if spec.output_folder:
        return base_dir / spec.output_folder
    return base_dir


def write_payload_to_spec(
    payload: dict[str, object],
    spec: ExportSpec,
    indent: int,
    urdf_path: Path,
    fallback_dir: str = "",
) -> Path:
    output_dir = resolve_export_dir(spec, fallback_dir=fallback_dir)

    copy_meshes_from_payload(payload, spec, urdf_path)

    if spec.mesh_prefix:
        rewrite_mesh_paths(
            payload,
            mesh_prefix=spec.mesh_prefix or "",
        )

    inertials_subpath = f"inertials/{spec.inertials_name}.yaml"
    if spec.configs_layout == "tree":
        write_tree_payload(
            output_dir,
            payload,
            indent,
            inertials_subpath=inertials_subpath,
            content=spec.content,
            existing_config=spec.existing_config,
            existing_inertials=spec.existing_inertials,
        )
    else:
        write_export_payload(
            output_dir,
            payload,
            indent,
            inertials_subpath=inertials_subpath,
            content=spec.content,
            existing_config=spec.existing_config,
            existing_inertials=spec.existing_inertials,
        )

    return output_dir


def collect_subtree_from_root(
    root_link: str,
    outgoing_joint_map: dict[str, list[dict[str, object]]],
) -> tuple[list[str], list[dict[str, object]]]:
    ordered_links: list[str] = []
    ordered_joints: list[dict[str, object]] = []
    visited_links: set[str] = set()
    visited_joints: set[str] = set()

    def walk(link_name: str) -> None:
        if link_name not in visited_links:
            visited_links.add(link_name)
            ordered_links.append(link_name)

        for joint in outgoing_joint_map.get(link_name, []):
            joint_name = str(joint["name"])
            child_link = str(joint["child"])

            if joint_name in visited_joints:
                continue

            visited_joints.add(joint_name)
            ordered_joints.append(joint)
            walk(child_link)

    walk(root_link)
    return ordered_links, ordered_joints


def build_export_payload(
    ordered_raw_links: list[str],
    ordered_raw_joints: list[dict[str, object]],
    raw_links: OrderedDict[str, dict[str, object]],
    reference_descriptors: list[OrderedDict] | None = None,
) -> dict[str, object]:
    link_name_map = OrderedDict()
    for index, raw_name in enumerate(ordered_raw_links):
        link_name_map[raw_name] = canonical_link_name(index)

    joint_name_map = OrderedDict()
    for index, joint in enumerate(ordered_raw_joints):
        joint_name_map[str(joint["name"])] = canonical_joint_name(index)

    topology = OrderedDict()
    topology["links"] = [link_name_map[raw_name]
                         for raw_name in ordered_raw_links]
    topology["joints"] = OrderedDict()

    inertials = OrderedDict()
    visuals = OrderedDict()
    collisions = OrderedDict()
    joint_origins = OrderedDict()
    joint_axes = OrderedDict()
    joint_limits = OrderedDict()
    joint_mimics = OrderedDict()
    reference_points = OrderedDict()

    for raw_link_name in ordered_raw_links:
        canonical_name = link_name_map[raw_link_name]
        link_record = raw_links[raw_link_name]

        if "inertial" in link_record:
            inertials[canonical_name] = link_record["inertial"]
        if "visual" in link_record:
            visuals[canonical_name] = link_record["visual"]
        if "collision" in link_record:
            collisions[canonical_name] = link_record["collision"]

    for raw_joint in ordered_raw_joints:
        raw_joint_name = str(raw_joint["name"])
        canonical_joint = joint_name_map[raw_joint_name]
        canonical_parent = link_name_map[str(raw_joint["parent"])]
        canonical_child = link_name_map[str(raw_joint["child"])]

        topology["joints"][canonical_joint] = OrderedDict(
            [
                ("type", str(raw_joint["type"])),
                ("parent", canonical_parent),
                ("child", canonical_child),
            ]
        )

        joint_origins[canonical_joint] = OrderedDict(
            [("origin", raw_joint["origin"])])
        joint_axes[canonical_joint] = OrderedDict(
            [("axis", raw_joint["axis"])])
        if "limit" in raw_joint:
            joint_limits[canonical_joint] = OrderedDict(
                [("limit", raw_joint["limit"])])
        if "mimic" in raw_joint:
            raw_mimic = raw_joint["mimic"]
            joint_mimics[canonical_joint] = OrderedDict(
                [
                    ("joint", joint_name_map[str(raw_mimic["joint"])]),
                    ("multiplier", raw_mimic["multiplier"]),
                    ("offset", raw_mimic["offset"]),
                ]
            )

    name_mapping = OrderedDict(
        [
            (
                "links",
                OrderedDict(
                    [
                        (
                            "canonical_to_original",
                            ordered_mapping(
                                [(canonical, raw) for raw, canonical in link_name_map.items()]),
                        ),
                        (
                            "original_to_canonical",
                            ordered_mapping(
                                [(raw, canonical) for raw, canonical in link_name_map.items()]),
                        ),
                    ]
                ),
            ),
            (
                "joints",
                OrderedDict(
                    [
                        (
                            "canonical_to_original",
                            ordered_mapping(
                                [(canonical, raw) for raw, canonical in joint_name_map.items()]),
                        ),
                        (
                            "original_to_canonical",
                            ordered_mapping(
                                [(raw, canonical) for raw, canonical in joint_name_map.items()]),
                        ),
                    ]
                ),
            ),
        ]
    )

    for descriptor in reference_descriptors or []:
        source_joint_name = str(descriptor["source_joint_name"])
        parent_link_name = str(descriptor["parent_link_name"])
        child_link_name = str(descriptor["child_link_name"])
        frame_parent_link_name = str(descriptor["frame_parent_link_name"])

        reference_entry = OrderedDict(
            [
                ("parent", link_name_map.get(frame_parent_link_name)),
                ("origin", descriptor["frame_origin"]),
                (
                    "meta",
                    OrderedDict(
                        [
                            ("note", reference_note_for_kind(
                                str(descriptor["kind"]))),
                            (
                                "source_joint",
                                OrderedDict(
                                    [
                                        ("original_name", source_joint_name),
                                        ("canonical_name", joint_name_map.get(
                                            source_joint_name)),
                                        ("type",
                                         descriptor["source_joint_type"]),
                                    ]
                                ),
                            ),
                            (
                                "parent_link",
                                OrderedDict(
                                    [
                                        ("original_name", parent_link_name),
                                        ("canonical_name", link_name_map.get(
                                            parent_link_name)),
                                    ]
                                ),
                            ),
                            (
                                "child_link",
                                OrderedDict(
                                    [
                                        ("original_name", child_link_name),
                                        ("canonical_name", link_name_map.get(
                                            child_link_name)),
                                    ]
                                ),
                            ),
                        ]
                    ),
                ),
            ]
        )

        reference_points[str(descriptor["name"])] = reference_entry

    return {
        "topology": topology,
        "name_mapping": name_mapping,
        "reference_points": reference_points,
        "joint_origins": joint_origins,
        "joint_axes": joint_axes,
        "joint_limits": joint_limits,
        "joint_mimics": joint_mimics,
        "inertials": inertials,
        "visuals": visuals,
        "collisions": collisions,
        "link_name_map": link_name_map,
        "joint_name_map": joint_name_map,
    }


def write_export_payload(
    output_dir: Path,
    payload: dict[str, object],
    indent: int,
    inertials_subpath: str = "inertials/nominal.yaml",
    content: str = "all",
    existing_config: str = "prompt",
    existing_inertials: str = "prompt",
) -> None:
    inertials_path = resolve_existing_path(
        output_dir / inertials_subpath, existing_inertials, "inertials file")
    if inertials_path is not None:
        write_yaml(inertials_path, payload["inertials"], indent)

    if content == "inertials":
        return

    flat_paths = [
        ("topology.yaml", payload["topology"]),
        ("name_mapping.yaml", payload["name_mapping"]),
        ("reference_points.yaml", payload["reference_points"]),
        ("joint_origins.yaml", payload["joint_origins"]),
        ("joint_axes.yaml", payload["joint_axes"]),
        ("joint_limits.yaml", payload["joint_limits"]),
        ("joint_mimics.yaml", payload["joint_mimics"]),
        ("visuals.yaml", payload["visuals"]),
        ("collisions.yaml", payload["collisions"]),
    ]
    for relative_path, data in flat_paths:
        target = resolve_existing_path_without_number(
            output_dir / relative_path, existing_config, "config file")
        if target is not None:
            write_yaml(target, data, indent)


def write_tree_payload(
    tree_root: Path,
    payload: dict[str, object],
    indent: int,
    inertials_subpath: str = "inertials/nominal.yaml",
    content: str = "all",
    existing_config: str = "prompt",
    existing_inertials: str = "prompt",
) -> None:
    inertials_path = resolve_existing_path(
        tree_root / inertials_subpath, existing_inertials, "inertials file")
    if inertials_path is not None:
        write_yaml(inertials_path, payload["inertials"], indent)

    if content == "inertials":
        return

    tree_paths = [
        (Path("struct") / "topology.yaml", payload["topology"]),
        (Path("struct") / "name_mapping.yaml", payload["name_mapping"]),
        (Path("struct") / "reference_points.yaml",
         payload["reference_points"]),
        (Path("joint") / "joint_origins.yaml", payload["joint_origins"]),
        (Path("joint") / "joint_axes.yaml", payload["joint_axes"]),
        (Path("joint") / "joint_limits.yaml", payload["joint_limits"]),
        (Path("joint") / "joint_mimics.yaml", payload["joint_mimics"]),
        (Path("link") / "visuals.yaml", payload["visuals"]),
        (Path("link") / "collisions.yaml", payload["collisions"]),
    ]
    for relative_path, data in tree_paths:
        target = resolve_existing_path_without_number(
            tree_root / relative_path, existing_config, "config file")
        if target is not None:
            write_yaml(target, data, indent)


def build_split_reference_payload(
    split_joint: dict[str, object],
    split_reference_mode: str,
    primary_payload: dict[str, object],
    reference_name: str,
) -> OrderedDict:
    primary_link_name_map = primary_payload["link_name_map"]
    primary_joint_name_map = primary_payload["joint_name_map"]

    raw_joint_name = str(split_joint["name"])
    raw_parent_link = str(split_joint["parent"])
    raw_child_link = str(split_joint["child"])

    if split_reference_mode == "create_virtual":
        boundary_parent_link = raw_child_link
        boundary_origin = ordered_origin((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        boundary_note = (
            "Virtual split boundary created after the selected joint. "
            "The exported topology keeps the original split joint, and this "
            "reference point behaves like a virtual fixed boundary attached to "
            "the split joint child frame."
        )
    else:
        boundary_parent_link = raw_parent_link
        boundary_origin = split_joint["origin"]
        boundary_note = "Split boundary uses the selected fixed joint directly."

    boundary = OrderedDict(
        [
            ("parent", primary_link_name_map.get(boundary_parent_link)),
            ("origin", boundary_origin),
            (
                "meta",
                OrderedDict(
                    [
                        ("note", boundary_note),
                        ("boundary_mode", split_reference_mode),
                        (
                            "source_joint",
                            OrderedDict(
                                [
                                    ("original_name", raw_joint_name),
                                    ("canonical_name", primary_joint_name_map.get(
                                        raw_joint_name)),
                                    ("type", str(split_joint["type"])),
                                ]
                            ),
                        ),
                        (
                            "parent_link",
                            OrderedDict(
                                [
                                    ("original_name", raw_parent_link),
                                    ("canonical_name", primary_link_name_map.get(
                                        raw_parent_link)),
                                ]
                            ),
                        ),
                        (
                            "child_link",
                            OrderedDict(
                                [
                                    ("original_name", raw_child_link),
                                    ("canonical_name", primary_link_name_map.get(
                                        raw_child_link)),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
        ]
    )

    if split_reference_mode == "create_virtual":
        boundary["meta"]["virtual_fixed_joint"] = OrderedDict(
            [
                ("original_name", f"{raw_joint_name}__virtual_split_joint"),
                ("canonical_name", None),
                ("type", "fixed"),
                (
                    "parent_link",
                    OrderedDict(
                        [
                            ("original_name", raw_child_link),
                            ("canonical_name", primary_link_name_map.get(
                                raw_child_link)),
                        ]
                    ),
                ),
                ("origin", ordered_origin((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))),
            ]
        )

    return OrderedDict([(reference_name, boundary)])


def merge_split_reference_point(
    primary_payload: dict[str, object],
    split_joint: dict[str, object],
    split_reference_mode: str,
) -> None:
    if split_reference_mode == "use_joint" and str(split_joint["type"]) != "fixed":
        raise ValueError(
            "--split-reference-mode use_joint requires the split joint to be fixed.")

    base_name = normalize_reference_name(str(split_joint["name"]))
    if base_name.endswith("_joint"):
        base_name = base_name[:-6]
    reference_name = f"{base_name}_split_point"
    if reference_name in primary_payload["reference_points"]:
        index = 2
        while f"{reference_name}_{index}" in primary_payload["reference_points"]:
            index += 1
        reference_name = f"{reference_name}_{index}"

    split_reference = build_split_reference_payload(
        split_joint=split_joint,
        split_reference_mode=split_reference_mode,
        primary_payload=primary_payload,
        reference_name=reference_name,
    )
    primary_payload["reference_points"].update(split_reference)


def filter_links_and_joints_for_references(
    raw_links: OrderedDict[str, dict[str, object]],
    raw_joints: list[dict[str, object]],
) -> tuple[OrderedDict[str, dict[str, object]], list[dict[str, object]], list[OrderedDict]]:
    excluded_links, excluded_joints, reference_descriptors = detect_terminal_reference_points(
        raw_links, raw_joints)
    filtered_links = OrderedDict(
        (link_name, link_record)
        for link_name, link_record in raw_links.items()
        if link_name not in excluded_links
    )
    filtered_joints = [joint for joint in raw_joints if str(
        joint["name"]) not in excluded_joints]
    return filtered_links, filtered_joints, reference_descriptors


def main() -> int:
    args = parse_args()

    urdf_path = Path(args.urdf)
    primary_spec = ExportSpec(
        configs_layout=args.configs_layout,
        output_dir=args.output_dir.strip(),
        output_folder=args.output_folder.strip(),
        inertials_name=args.inertials_name.strip() or "nominal",
        content=args.content,
        mesh_prefix=args.mesh_prefix.strip(),
        mesh_copy_to=args.mesh_copy_to.strip(),
        existing_config=args.existing_config,
        existing_mesh=args.existing_mesh,
        existing_inertials=args.existing_inertials,
    )
    subtree_spec = ExportSpec(
        configs_layout=args.subtree_configs_layout,
        output_dir=args.subtree_output_dir.strip(),
        output_folder=args.subtree_output_folder.strip(),
        inertials_name=args.subtree_inertials_name.strip() or "nominal",
        content=args.subtree_content,
        mesh_prefix=args.subtree_mesh_prefix.strip(),
        mesh_copy_to=args.subtree_mesh_copy_to.strip(),
        existing_config=args.existing_config,
        existing_mesh=args.existing_mesh,
        existing_inertials=args.existing_inertials,
    )

    include_links = csv_arg(args.include_links)
    exclude_links = csv_arg(args.exclude_links)
    include_joints = csv_arg(args.include_joints)
    exclude_joints = csv_arg(args.exclude_joints)
    root_link_arg = args.root_link.strip()
    truncate_at_joint = args.truncate_at_joint.strip()
    validate_export_spec(primary_spec, "primary export")
    if args.save_subtree:
        validate_optional_export_spec(subtree_spec, "subtree export")

    tree = ET.parse(urdf_path)
    robot = tree.getroot()

    raw_links: OrderedDict[str, dict[str, object]] = OrderedDict()
    raw_joints: list[dict[str, object]] = []

    for link in robot.findall("link"):
        name = link.get("name")
        if not name or not should_keep(name, include_links, exclude_links):
            continue

        link_record: dict[str, object] = {}

        inertial = link.find("inertial")
        if inertial is not None:
            mass = inertial.find("mass")
            inertia = inertial.find("inertia")
            inertial_entry = OrderedDict()
            inertial_entry["origin"] = parse_origin(inertial.find("origin"))
            inertial_entry["mass"] = float(
                mass.get("value")) if mass is not None else 0.0
            if inertia is not None:
                inertial_entry["inertia"] = OrderedDict(
                    [
                        ("xx", float(inertia.get("ixx", "0.0"))),
                        ("xy", float(inertia.get("ixy", "0.0"))),
                        ("xz", float(inertia.get("ixz", "0.0"))),
                        ("yy", float(inertia.get("iyy", "0.0"))),
                        ("yz", float(inertia.get("iyz", "0.0"))),
                        ("zz", float(inertia.get("izz", "0.0"))),
                    ]
                )
            link_record["inertial"] = inertial_entry

        visual = link.find("visual")
        if visual is not None:
            link_record["visual"] = OrderedDict(
                [
                    ("origin", parse_origin(visual.find("origin"))),
                    ("geometry", extract_geometry(visual)),
                ]
            )

        collision = link.find("collision")
        if collision is not None:
            link_record["collision"] = OrderedDict(
                [
                    ("origin", parse_origin(collision.find("origin"))),
                    ("geometry", extract_geometry(collision)),
                ]
            )

        raw_links[name] = link_record

    for joint in robot.findall("joint"):
        name = joint.get("name")
        joint_type = joint.get("type")
        parent_el = joint.find("parent")
        child_el = joint.find("child")
        if not name or not joint_type or parent_el is None or child_el is None:
            continue

        parent = parent_el.get("link")
        child = child_el.get("link")
        if not parent or not child:
            continue

        if not should_keep(name, include_joints, exclude_joints):
            continue
        if not filter_joint_by_links(parent, child, include_links, exclude_links):
            continue
        if parent not in raw_links or child not in raw_links:
            continue

        joint_record: dict[str, object] = OrderedDict(
            [
                ("name", name),
                ("type", joint_type),
                ("parent", parent),
                ("child", child),
            ]
        )

        joint_record["origin"] = parse_origin(joint.find("origin"))

        axis = joint.find("axis")
        joint_record["axis"] = ordered_xyz(
            *parse_xyz_attr(axis.get("xyz") if axis is not None else None, (0.0, 0.0, 0.0))
        )

        limit = joint.find("limit")
        if limit is not None:
            joint_record["limit"] = OrderedDict(
                [
                    ("lower", maybe_float(limit.get("lower"))),
                    ("upper", maybe_float(limit.get("upper"))),
                    ("effort", maybe_float(limit.get("effort"))),
                    ("velocity", maybe_float(limit.get("velocity"))),
                ]
            )

        mimic = joint.find("mimic")
        if mimic is not None and mimic.get("joint"):
            joint_record["mimic"] = OrderedDict(
                [
                    ("joint", str(mimic.get("joint"))),
                    ("multiplier", maybe_float(mimic.get("multiplier"))
                     if mimic.get("multiplier") is not None else 1.0),
                    ("offset", maybe_float(mimic.get("offset"))
                     if mimic.get("offset") is not None else 0.0),
                ]
            )

        raw_joints.append(joint_record)

    if truncate_at_joint and truncate_at_joint not in {str(joint["name"]) for joint in raw_joints}:
        raise ValueError(
            f"Requested truncate joint '{truncate_at_joint}' was not found after filtering.")
    if args.save_subtree and not truncate_at_joint:
        raise ValueError(
            "--save-subtree requires --truncate-at-joint so the split boundary is explicit.")

    filtered_links, filtered_joints, reference_descriptors = filter_links_and_joints_for_references(
        raw_links,
        raw_joints,
    )

    root_link = find_root_link(filtered_joints, root_link_arg)
    if root_link not in filtered_links:
        raise ValueError(
            f"Root link '{root_link}' is not present after filtering.")

    filtered_outgoing_joint_map = build_outgoing_joint_map(filtered_joints)
    if args.save_subtree and truncate_at_joint and args.split_reference_mode == "create_virtual":
        ordered_raw_links, ordered_raw_joints = traverse_tree_with_virtual_split(
            root_link=root_link,
            outgoing_joint_map=filtered_outgoing_joint_map,
            truncate_at_joint=truncate_at_joint,
        )
    else:
        ordered_raw_links, ordered_raw_joints = traverse_tree(
            root_link=root_link,
            outgoing_joint_map=filtered_outgoing_joint_map,
            truncate_at_joint=truncate_at_joint,
        )

    primary_payload = build_export_payload(
        ordered_raw_links,
        ordered_raw_joints,
        filtered_links,
        reference_descriptors=reference_descriptors,
    )

    if args.save_subtree:
        split_joint = next(joint for joint in raw_joints if str(
            joint["name"]) == truncate_at_joint)
        merge_split_reference_point(
            primary_payload=primary_payload,
            split_joint=split_joint,
            split_reference_mode=args.split_reference_mode,
        )

    output_dir = write_payload_to_spec(
        primary_payload, primary_spec, args.indent, urdf_path)

    if args.save_subtree:
        subtree_root_link = str(split_joint["child"])
        subtree_raw_links_ordered, subtree_raw_joints = collect_subtree_from_root(
            root_link=subtree_root_link,
            outgoing_joint_map=build_outgoing_joint_map(raw_joints),
        )
        subtree_raw_links = OrderedDict(
            (link_name, raw_links[link_name]) for link_name in subtree_raw_links_ordered)
        subtree_filtered_links, subtree_filtered_joints, subtree_reference_descriptors = filter_links_and_joints_for_references(
            subtree_raw_links,
            subtree_raw_joints,
        )
        subtree_root_link = find_root_link(
            subtree_filtered_joints, subtree_root_link)
        if subtree_root_link not in subtree_filtered_links:
            raise ValueError(
                f"Subtree root link '{subtree_root_link}' is not present after filtering.")
        subtree_ordered_links, subtree_ordered_joints = traverse_tree(
            root_link=subtree_root_link,
            outgoing_joint_map=build_outgoing_joint_map(
                subtree_filtered_joints),
            truncate_at_joint="",
        )
        subtree_payload = build_export_payload(
            subtree_ordered_links,
            subtree_ordered_joints,
            subtree_filtered_links,
            reference_descriptors=subtree_reference_descriptors,
        )
        subtree_output_dir = write_payload_to_spec(
            subtree_payload,
            subtree_spec,
            args.indent,
            urdf_path,
            fallback_dir=f"{output_dir}_subtree",
        )

    print(f"Wrote extracted parameter files to: {output_dir}")
    if args.save_subtree:
        print(f"Wrote subtree parameter files to: {subtree_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
