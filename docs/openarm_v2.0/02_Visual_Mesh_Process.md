# Visual Mesh Process

This workflow batch-processes visual DAE meshes. It repairs and welds selected open-face parts, removes small components such as screws, clusters the remaining geometry by dominant color, and exports OBJ groups, a repaired DAE, optional STL files, and a MuJoCo preview XML.

The stable entry point for this workflow is:

```text
scripts/src/visual_mesh_batch_process.py
```

The batch script calls Blender in background mode and runs:

```text
scripts/src/visual_mesh_merge_and_cluster.py
```

The standalone mesh utilities documented in `05_Mesh_Tools.md` do not replace
this workflow. Use them only for separate STL/OBJ experiments or manual mesh
cleanup.

## Prerequisites

Install Blender and make sure it is available from the command line:

```bash
blender --version
```

If Blender is not in `PATH`, pass its executable path with `--blender`.
See `06_Environment_Setup.md` for the recommended Blender 4.3.2 and Python
environment setup.

## Usage

Preview the planned files and output paths:

```bash
python scripts/src/visual_mesh_batch_process.py assets/robot/openarm_v2.0/meshes/arm/visual --dry-run
```

Development/review mode. This does not replace source DAE files and also writes review files under `review/`:

```bash
python scripts/src/visual_mesh_batch_process.py assets/robot/openarm_v2.0/meshes/arm/visual --dev
```

After checking the results, replace the source DAE files:

```bash
python scripts/src/visual_mesh_batch_process.py assets/robot/openarm_v2.0/meshes/arm/visual --replace
```

Optionally export repaired STL files next to the DAE outputs:

```bash
python scripts/src/visual_mesh_batch_process.py assets/robot/openarm_v2.0/meshes/arm/visual --export-stl
```

Collect the final grouped DAE/STL outputs into a separate folder without
replacing the source files:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --export-stl \
  --final-output-root assets/robot/openarm_v2.0/meshes/arm/visual/final
```

Manual delete entries can be supplied with a YAML file after reviewing `review/keep/`.
The YAML root is a mapping. Each key can be the DAE stem, the output prefix, or the short part name with `_obj` removed. Each value is one or more repair unit names from `review/keep/`, without the `.obj` or `.mtl` suffix.

Recommended list form:

```yaml
link1_obj:
  - link1_obj_repair_004
  - link1_obj_repair_031

link3_obj:
  - link3_obj_repair_004
```

Equivalent key forms for a file such as `link1_filtered.dae` are all accepted:

```yaml
# output prefix
link1_obj:
  - link1_obj_repair_031

# DAE stem
link1_filtered:
  - link1_obj_repair_031

# short part name
link1:
  - link1_obj_repair_031
```

Inline values are also accepted:

```yaml
link1_obj: [link1_obj_repair_004, link1_obj_repair_031]
link3_obj: link3_obj_repair_004, link3_obj_repair_008
```

```bash
python scripts/src/visual_mesh_batch_process.py assets/robot/openarm_v2.0/meshes/arm/visual --manual-delete-yaml manual_delete.yaml
```

Manual delete units can also be passed directly on the command line. This
applies to every DAE processed by the batch run:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --manual-delete link3_obj_repair_004 \
  --manual-delete link3_obj_repair_008
```

When `--replace` is used, the original DAE is backed up to a `source/` directory next to the processed result root:

```text
source/<original_name>.dae
```

## Quality / Effect Control

The default visual workflow is conservative. For important parts, run `--dev`
first, inspect `review/keep/`, `review/delete/`, and
`review/analysis_report.tsv`, then rerun with tuned thresholds.

Stricter open-boundary contact repair. Use this when separate open-face pieces
are being welded too easily:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --dev \
  --contact-tol 5e-6 \
  --min-matches 40 \
  --min-match-ratio 0.08 \
  --boundary-dedupe-distance 5e-7
```

More permissive contact repair. Use this when expected open-contact pieces stay
separate:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --dev \
  --contact-tol 2e-5 \
  --min-matches 10 \
  --min-match-ratio 0.02
```

Control small-component deletion. Lower thresholds keep more details; higher
thresholds remove more small screw-like or artifact-like parts:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --dev \
  --delete-max-diag 0.02 \
  --delete-max-area 0.001 \
  --delete-max-dim 0.015 \
  --delete-max-faces 3000
```

Control material/color grouping. Smaller `--color-threshold` creates more OBJ
groups; larger values merge nearby material colors:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --color-threshold 0.05 \
  --export-stl
```

For debugging Blender import/export cleanup effects, disable cleanup passes one
at a time. Import cleanup dissolves degenerate geometry on each original leaf
mesh and recalculates normals only for closed meshes; it intentionally avoids
global vertex merging. Export cleanup removes loose edges/vertices that can
become **Collada `<lines>`** and dissolves degenerate geometry before OBJ/DAE
export:

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --dev \
  --no-import-cleanup
```

```bash
python scripts/src/visual_mesh_batch_process.py \
  assets/robot/openarm_v2.0/meshes/arm/visual \
  --dev \
  --no-export-cleanup
```

## Outputs

The default output directory is:

```text
<input_dir>/processed/<dae_stem>_obj/
```

Main outputs:

```text
<dae_stem>_00.obj/.mtl
<dae_stem>_01.obj/.mtl
<dae_stem>_filtered.dae
<dae_stem>_filtered_grouped.dae
<prefix>_mujoco_preview.xml
<prefix>_repair_color_report.txt
```

Extra outputs with `--export-stl`:

```text
<dae_stem>_filtered.stl
<dae_stem>_filtered_grouped.stl
```

Extra copies with `--final-output-root <dir>`:

```text
<dir>/<source_name>.dae
<dir>/<source_name>.stl   # when --export-stl was used
```

Extra outputs with `--dev`:

```text
review/keep/
review/delete/
review/analysis_report.tsv
review/delete_candidates.txt
```

## Key Parameters

- `--parent-depth`: controls how imported scene hierarchy is grouped before
  repair analysis. Batch default: `1`.
- `--prefix-suffix`: suffix appended to each DAE stem to form the processing
  prefix and output folder name. Batch default: `_obj`.
- `--merge-distance`: temporarily merges very close vertices on a bmesh copy for contact detection. If the temporary merged mesh has no boundary vertices, the part is treated as having no open-contact boundary for grouping. It does not globally modify every exported mesh. Batch default: `1e-6`.
- `--contact-tol`: detects contact between open mesh boundaries and is also used for boundary welding after grouping. Batch default: `1e-5`.
- `--min-matches`: minimum number of matching boundary points required to treat two open meshes as connected. Batch default: `20`.
- `--min-match-ratio`: additional ratio-based contact threshold after boundary points are deduplicated. Batch default: `0.05`.
- `--boundary-dedupe-distance`: distance used to deduplicate boundary vertices before contact matching. Batch default: `1e-6`.
- `--min-repair-depth`: minimum hierarchy depth for repair grouping. Batch
  default: `0`.
- `--no-import-cleanup`: skip the post-import conservative cleanup pass.
- `--no-export-cleanup`: skip the final cleanup pass before OBJ/DAE export.
- `--export-stl`: also export filtered and final grouped STL files next to the DAE outputs.
- `--final-output-root`: copy final grouped DAE/STL outputs into a separate folder using the original source file stem/name. In recursive mode, paths relative to `input_dir` are preserved.
- `--manual-delete-yaml`: batch-mode YAML mapping from DAE stem, prefix, or short part name to repair units that should be force-deleted.
- `--manual-delete`: force-delete one or more repair unit names for every DAE
  in the batch run. Can be repeated or supplied as comma-separated values.
- `--color-threshold`: material color clustering threshold.
- `--delete-max-diag / --delete-max-area / --delete-max-dim / --delete-max-faces`: absolute thresholds for small-component deletion candidates.
- `--recursive`: recursively process DAE files under subdirectories.
- `--output-root`: override the result root directory. Default: `<input_dir>/processed`.

Note on defaults: `visual_mesh_merge_and_cluster.py` has its own direct-run
defaults, but the documented workflow uses `visual_mesh_batch_process.py`.
The batch script passes its current values explicitly to the Blender processor,
so the batch defaults above are the effective defaults for this workflow.

## Processing Logic

1. Import the DAE in Blender and collect leaf mesh objects.
2. Apply conservative cleanup to each original mesh.
3. Group meshes by scene hierarchy to avoid merging unrelated parts.
4. Detect contacts between open mesh boundary vertices and create repair units.
5. Weld boundary vertices for accepted open-contact groups. The script does not run boolean operations or fill holes.
6. Mark and remove small-component candidates using absolute bbox, area, and face-count thresholds.
7. Cluster the remaining repair units by dominant material color. The cluster color is taken from the largest-area representative color.
8. Export the filtered DAE before color grouping, and optionally a filtered STL.
9. Export color-grouped OBJ files, the filtered/color-grouped DAE, optional grouped STL, a MuJoCo preview XML, and a report.
10. In `--replace` mode, back up the source DAE under `source/` and replace it
    with the grouped DAE. With `--final-output-root`, copy grouped DAE/STL files
    to that folder without changing the source.
