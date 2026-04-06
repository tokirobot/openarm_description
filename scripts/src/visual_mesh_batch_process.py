import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Batch process all DAE files in a folder with merge_and_cluster.py. "
            "By default, repaired meshes are written to per-link result folders "
            "without changing source DAE files. With --replace, each source DAE "
            "is backed up into the source/ folder next to the output root and replaced with the "
            "repaired grouped DAE. With --dev, review files are also written."
        )
    )
    parser.add_argument(
        "input_path",
        type=Path,
        help="Input DAE file or directory containing DAE files.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Write review outputs.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace source DAE files after successful processing.",
    )
    parser.add_argument(
        "--blender",
        default=r"blender",
        help="Path to Blender executable, or blender if it is on PATH.",
    )
    parser.add_argument(
        "--processor",
        type=Path,
        default=Path(__file__).with_name("visual_mesh_merge_and_cluster.py"),
        help="Path to merge_and_cluster.py.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root folder for per-link processing results. Default: input_dir/processed.",
    )
    parser.add_argument(
        "--final-output-root",
        type=Path,
        default=None,
        help=(
            "Optional folder to collect final grouped DAE/STL outputs. "
            "Files are copied with the original source stem/name; recursive "
            "mode preserves paths relative to input_dir."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process DAE files recursively under input_dir.",
    )
    parser.add_argument(
        "--prefix-suffix",
        default="_obj",
        help="Suffix appended to each DAE stem to form the processing prefix.",
    )
    parser.add_argument("--parent-depth", type=int, default=1)
    parser.add_argument("--contact-tol", type=float, default=1e-5)
    parser.add_argument("--min-matches", type=int, default=20)
    parser.add_argument("--min-match-ratio", type=float, default=0.05)
    parser.add_argument("--boundary-dedupe-distance", type=float, default=1e-6)
    parser.add_argument("--merge-distance", type=float, default=1e-6)
    parser.add_argument("--min-repair-depth", type=int, default=0)
    parser.add_argument("--color-threshold", type=float, default=0.08)
    parser.add_argument(
        "--no-import-cleanup",
        dest="import_cleanup",
        action="store_false",
        help="Pass through to skip conservative cleanup after importing each DAE.",
    )
    parser.set_defaults(import_cleanup=True)
    parser.add_argument(
        "--no-export-cleanup",
        dest="export_cleanup",
        action="store_false",
        help="Pass through to skip final cleanup before exporting OBJ/DAE.",
    )
    parser.set_defaults(export_cleanup=True)
    parser.add_argument("--delete-max-diag", type=float, default=0.03)
    parser.add_argument("--delete-max-area", type=float, default=0.002)
    parser.add_argument("--delete-max-dim", type=float, default=0.025)
    parser.add_argument("--delete-max-faces", type=int, default=5000)
    parser.add_argument(
        "--export-stl",
        action="store_true",
        help="Pass through to also export filtered/grouped STL files.",
    )
    parser.add_argument(
        "--manual-delete-yaml",
        type=Path,
        default=None,
        help=(
            "YAML file mapping each DAE stem, prefix, or short part name to "
            "repair unit names that should be force-deleted."
        ),
    )
    parser.add_argument(
        "--manual-delete",
        action="append",
        default=[],
        help=(
            "Repair unit name to force-delete for every processed DAE. "
            "Can be used multiple times or as a comma-separated list."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands and replacements without running Blender or changing files.",
    )
    return parser.parse_args()


def iter_dae_files(input_dir: Path, recursive: bool, output_root: Path):
    pattern = "**/*.dae" if recursive else "*.dae"
    files = []

    for path in input_dir.glob(pattern):
        if not path.is_file():
            continue
        stem = path.stem
        if (
            stem.endswith("_source")
            or stem.endswith("_grouped")
            or "_repaired" in stem
            or "_after_delete" in stem
            or "_color_" in stem
        ):
            continue

        try:
            path.relative_to(output_root)
            continue
        except ValueError:
            pass

        files.append(path)

    return sorted(files)


def collect_dae_files(input_path: Path, recursive: bool, output_root: Path):
    if input_path.is_file():
        if input_path.suffix.lower() != ".dae":
            raise SystemExit(f"Input file is not a DAE file: {input_path}")
        return [input_path]

    if input_path.is_dir():
        return iter_dae_files(input_path, recursive, output_root)

    raise SystemExit(f"Input path does not exist: {input_path}")


def normalize_manual_delete_value(value):
    if value is None:
        return []

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(normalize_manual_delete_value(item))
        return out

    return [str(value).strip()] if str(value).strip() else []


def clean_manual_delete_key(key):
    return str(key).strip().strip("\ufeff").strip("'\"")


def parse_inline_yaml_list(value):
    value = value.strip()

    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]

    return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]


def load_manual_delete_yaml(path: Path):
    if path is None:
        return {}

    if not path.is_file():
        raise FileNotFoundError(f"Manual delete YAML does not exist: {path}")

    try:
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not isinstance(data, dict):
            raise ValueError("Manual delete YAML root must be a mapping.")

        return {
            clean_manual_delete_key(key): normalize_manual_delete_value(value)
            for key, value in data.items()
        }
    except ImportError:
        pass

    mapping = {}
    current_key = None

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].rstrip()

            if not line.strip():
                continue

            stripped = line.strip()

            if stripped.startswith("-"):
                if current_key is None:
                    raise ValueError(
                        f"List item without key in {path}: {raw_line.rstrip()}")

                item = stripped[1:].strip().strip("'\"")
                if item:
                    mapping.setdefault(current_key, []).append(item)
                continue

            if ":" not in stripped:
                raise ValueError(
                    f"Unsupported YAML line in {path}: {raw_line.rstrip()}")

            key, value = stripped.split(":", 1)
            current_key = clean_manual_delete_key(key)
            value = value.strip()
            mapping.setdefault(current_key, [])

            if value:
                mapping[current_key].extend(parse_inline_yaml_list(value))

    return mapping


def get_manual_delete_units(mapping, dae_path: Path, prefix: str):
    short_name = prefix[:-4] if prefix.endswith("_obj") else prefix
    units = []

    for key in (prefix, dae_path.stem, short_name):
        units.extend(mapping.get(key, []))

    seen = set()
    unique = []

    for unit in units:
        if unit not in seen:
            seen.add(unit)
            unique.append(unit)

    return unique


def build_blender_command(
    args,
    dae_path: Path,
    result_dir: Path,
    prefix: str,
    dev: bool,
    manual_delete_units=None,
):
    manual_delete_units = manual_delete_units or []
    command = [
        str(args.blender),
        "--background",
        "--python",
        str(args.processor),
        "--",
        str(dae_path),
        str(result_dir),
        prefix,
        "--parent-depth",
        str(args.parent_depth),
        "--contact-tol",
        str(args.contact_tol),
        "--min-matches",
        str(args.min_matches),
        "--min-match-ratio",
        str(args.min_match_ratio),
        "--boundary-dedupe-distance",
        str(args.boundary_dedupe_distance),
        "--merge-distance",
        str(args.merge_distance),
        "--min-repair-depth",
        str(args.min_repair_depth),
        "--color-threshold",
        str(args.color_threshold),
        "--delete-max-diag",
        str(args.delete_max_diag),
        "--delete-max-area",
        str(args.delete_max_area),
        "--delete-max-dim",
        str(args.delete_max_dim),
        "--delete-max-faces",
        str(args.delete_max_faces),
    ]

    if manual_delete_units:
        command.extend(
            ["--manual-delete-units", ",".join(manual_delete_units)])

    if not args.import_cleanup:
        command.append("--no-import-cleanup")

    if not args.export_cleanup:
        command.append("--no-export-cleanup")

    if args.export_stl:
        command.append("--export-stl")

    if dev:
        command.append("--dev")

    return command


def replace_source_dae(dae_path: Path, result_dae: Path, source_root: Path):
    if not result_dae.exists():
        raise FileNotFoundError(
            f"Expected repaired DAE was not produced: {result_dae}")

    source_root.mkdir(parents=True, exist_ok=True)
    source_backup = source_root / dae_path.name
    tmp_replacement = dae_path.with_name(f".{dae_path.stem}.dae.tmp")

    if source_backup.exists():
        print(
            f"[WARN] Source backup already exists, keeping it unchanged: {source_backup}")
    else:
        shutil.copy2(dae_path, source_backup)

    try:
        shutil.copy2(result_dae, tmp_replacement)
        tmp_replacement.replace(dae_path)
    except Exception:
        if tmp_replacement.exists():
            tmp_replacement.unlink()
        raise

    return source_backup


def copy_final_outputs(
    dae_path: Path,
    input_dir: Path,
    final_output_root: Path,
    result_dae: Path,
    result_stl: Path,
):
    if not result_dae.exists():
        raise FileNotFoundError(
            f"Expected final grouped DAE was not produced: {result_dae}")

    try:
        relative_parent = dae_path.parent.relative_to(input_dir)
    except ValueError:
        relative_parent = Path()

    target_dir = final_output_root / relative_parent
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    dae_target = target_dir / dae_path.name
    shutil.copy2(result_dae, dae_target)
    copied.append(dae_target)

    if result_stl.exists():
        stl_target = target_dir / f"{dae_path.stem}.stl"
        shutil.copy2(result_stl, stl_target)
        copied.append(stl_target)

    return copied


def main():
    args = parse_args()
    input_path = args.input_path.resolve()
    processor = args.processor.resolve()
    input_dir = input_path if input_path.is_dir() else input_path.parent
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else input_dir / "processed"
    )
    final_output_root = (
        args.final_output_root.resolve()
        if args.final_output_root is not None
        else None
    )

    if not processor.is_file():
        raise SystemExit(f"Processor script does not exist: {processor}")

    try:
        manual_delete_map = load_manual_delete_yaml(args.manual_delete_yaml)
    except Exception as exc:
        raise SystemExit(f"Failed to read manual delete YAML: {exc}") from exc

    cli_manual_delete_units = normalize_manual_delete_value(args.manual_delete)
    dae_files = collect_dae_files(input_path, args.recursive, output_root)

    if not dae_files:
        print(f"[WARN] No DAE files found under {input_path}")
        return

    print(f"[INFO] Dev review outputs: {args.dev}")
    print(f"[INFO] Replace source DAE files: {args.replace}")
    print(f"[INFO] Input dir: {input_dir}")
    print(f"[INFO] Output root: {output_root}")
    if final_output_root is not None:
        print(f"[INFO] Final output root: {final_output_root}")
    print(f"[INFO] DAE count: {len(dae_files)}")
    if args.manual_delete_yaml:
        print(
            f"[INFO] Manual delete YAML: {args.manual_delete_yaml.resolve()}")
    if cli_manual_delete_units:
        print(f"[INFO] Manual delete units: {', '.join(cli_manual_delete_units)}")

    failures = []

    for dae_path in dae_files:
        prefix = f"{dae_path.stem}{args.prefix_suffix}"
        link_dir = output_root / prefix

        result_dir = link_dir

        result_dae = result_dir / f"{dae_path.stem}_filtered_grouped.dae"
        result_stl = result_dir / f"{dae_path.stem}_filtered_grouped.stl"
        manual_delete_units = get_manual_delete_units(
            manual_delete_map,
            dae_path=dae_path,
            prefix=prefix,
        )
        for unit in cli_manual_delete_units:
            if unit not in manual_delete_units:
                manual_delete_units.append(unit)

        command = build_blender_command(
            args=args,
            dae_path=dae_path,
            result_dir=result_dir,
            prefix=prefix,
            dev=args.dev,
            manual_delete_units=manual_delete_units,
        )

        print(f"\n[INFO] Processing: {dae_path.name}")
        print(f"[INFO] Prefix dir: {link_dir}")
        print(f"[INFO] Result dir: {result_dir}")
        if manual_delete_units:
            print(
                f"[INFO] Manual delete units: {', '.join(manual_delete_units)}")

        if args.dry_run:
            print(
                "[DRY-RUN] " + " ".join(f'"{part}"' if " " in part else part for part in command))
            if args.replace:
                print(
                    f"[DRY-RUN] Would copy {dae_path} -> {output_root.parent / 'source' / dae_path.name}")
                print(f"[DRY-RUN] Would replace {dae_path} with {result_dae}")
            if final_output_root is not None:
                try:
                    relative_parent = dae_path.parent.relative_to(input_dir)
                except ValueError:
                    relative_parent = Path()
                dry_target_dir = final_output_root / relative_parent
                print(
                    f"[DRY-RUN] Would copy {result_dae} -> {dry_target_dir / dae_path.name}")
                if args.export_stl:
                    print(
                        f"[DRY-RUN] Would copy {result_stl} -> {dry_target_dir / (dae_path.stem + '.stl')}")
            continue

        result_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(command, check=True)

            if args.replace:
                source_backup = replace_source_dae(
                    dae_path=dae_path,
                    result_dae=result_dae,
                    source_root=output_root.parent / "source",
                )
                print(f"[INFO] Source backup: {source_backup}")
                print(f"[INFO] Replaced source DAE: {dae_path}")

            if final_output_root is not None:
                copied = copy_final_outputs(
                    dae_path=dae_path,
                    input_dir=input_dir,
                    final_output_root=final_output_root,
                    result_dae=result_dae,
                    result_stl=result_stl,
                )
                for target in copied:
                    print(f"[INFO] Copied final output: {target}")

        except Exception as exc:
            failures.append((dae_path, exc))
            print(f"[ERROR] Failed processing {dae_path}: {exc}")

    if failures:
        print("\n[ERROR] Batch completed with failures:")
        for path, exc in failures:
            print(f"  - {path}: {exc}")
        raise SystemExit(1)

    print("\n[INFO] Batch completed successfully.")


if __name__ == "__main__":
    main()
