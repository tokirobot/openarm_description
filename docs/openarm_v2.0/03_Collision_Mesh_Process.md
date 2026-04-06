# Collision Mesh Process

This document records the current collision mesh processing flow for
OpenArm v2.0.

There are several collision mesh outputs used for comparison:

- Default coarse collision mesh: generated with Blender convex hull.
- Remeshed collision mesh: generated with OpenVDB, stored under `remeshed/`.
- Experimental CoACD merged mesh: generated with CoACD convex decomposition,
  then merged/remeshed back into one STL under `coacd_merged/`.
- Experimental trimesh/V-HACD mesh: generated with trimesh's VHACD wrapper,
  stored under `trimesh_vhacd/`.

The default URDF/config collision mesh should continue to use files directly
under `meshes/.../collision/`. The OpenVDB result is kept as an optional
alternative with the same file names under `meshes/.../collision/remeshed/`.
The standalone mesh utilities documented in `05_Mesh_Tools.md` do not replace
the collision workflows below. Use them only for separate STL/OBJ experiments
or manual cleanup.

For environment setup, including Blender 4.3.2, Python packages, and OpenVDB
`vdb_tool`, see `06_Environment_Setup.md`.

## Default: Blender Convex Hull

Script:

```bash
python scripts/src/collision_mesh_batch_process.py <input>
```

The batch script calls Blender in background mode and runs:

```text
scripts/src/collision_mesh_convex_hull.py
```

The Blender processor imports `.dae`, `.obj`, or `.stl`, joins all mesh
objects, cleans loose/degenerate geometry, applies Blender's convex hull
operation, and exports one STL.
In directory mode, the batch default is `--extensions dae,obj,stl`. Use
`--extensions dae` or `--extensions stl` when you want only one source type.

For DAE files with multiple visual nodes, `--per-node-hull` can build one
convex hull per imported mesh object first, then join those hulls into one STL.
This keeps separated sub-parts from being wrapped by one large hull.

The Blender processor can also cut the joined mesh into two pieces before hull
generation. The cut plane is perpendicular to `--split-axis`; its position is
computed from the farthest point on `--split-direction` and moved inward by
`--split-offset`. For example, `--split-axis x --split-direction positive
--split-offset 0.03` starts at max X and cuts at `max_x - 0.03`.

### Generate From Visual Meshes

Use this when collision meshes should be regenerated from visual meshes.
Outputs are written to `processed/` by default.

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/visual  \
    --extensions dae
```

Per-node hull mode:

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/visual  \
    --extensions dae \
    --per-node-hull
```

Split-cut hull mode:

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/visual/link3.dae \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/split_hull \
    --split-axis x \
    --split-direction positive \
    --split-offset 0.03
```

For `link3.dae -> link3.stl`, split-cut mode writes the joined two-hull result
to `link3.stl` and also keeps the intermediate split products:

```text
link3.stl                         # joined far hull + inner hull
link3_split_pos_x_far_raw.stl     # raw cut piece near max X
link3_split_pos_x_inner_raw.stl   # raw remaining cut piece
link3_split_pos_x_far_hull.stl    # convex hull of far piece
link3_split_pos_x_inner_hull.stl  # convex hull of inner piece
```

The `*_raw.stl` files are clipped inspection meshes and can be open on the cut
plane. The `*_hull.stl` files are the closed convex hulls used by the joined
result.

Split-cut mode cannot be combined with `--per-node-hull` or `--replace`.

Example output:

```text
assets/robot/openarm_v2.0/meshes/arm/visual/
  link3.dae
  processed/
    link3.stl
```

Use `--output-root` to write directly to another folder:

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/visual \
    --extensions dae \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision
```

### Replace Existing Collision STLs

Use this when the input directory already contains STL collision meshes and
the convex hull result should become the default collision mesh.

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --extensions stl \
    --replace
```

Replace mode only supports STL inputs. It writes a temporary convex hull STL,
backs up the original STL under `source/`, then replaces the source STL.

Example result:

```text
assets/robot/openarm_v2.0/meshes/arm/collision/
  link3.stl          # convex hull result, default collision mesh
  source/
    link3.stl        # original STL backup
```

Use `--dry-run` before replacing files:

```bash
python scripts/src/collision_mesh_batch_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --extensions stl \
    --replace \
    --dry-run
```

## Remeshed: OpenVDB

Script:

```bash
python scripts/src/collision_mesh_openvdb_process.py <input>
```

This script processes STL files only. It runs:

```text
vdb_tool -read input.stl -mesh2ls voxel=... width=... -close radius=... -ls2mesh adapt=... -write output.obj
```

Then it calls Blender through:

```text
scripts/src/blender_obj_to_stl.py
```

to convert the OpenVDB OBJ result into STL. By default, the batch script passes
`--remove-internal-voids` and `--fix-inverted-normals` to the converter. The
converter splits loose mesh islands, uses the largest absolute-volume island as
the outside reference, removes islands with the opposite signed volume, and
flips remaining negative-volume islands so exported STL normals face outward
for preview/rendering. The processed mesh is also written back to the
intermediate OBJ by default so the kept `remeshed/*.obj` matches the STL.
Disable these options if the mesh may intentionally contain separate shells
with inconsistent normals.

Default parameters:

```text
voxel = 0.0010
width = 23
close radius = 18
adapt = 0.01
```

### Generate Remeshed Collision Meshes

Run from the collision directory:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision 
```

Default output:

```text
assets/robot/openarm_v2.0/meshes/arm/collision/
  link3.stl
  remeshed/
    link3.obj
    link3.stl
```

The OpenVDB script does not replace source STLs. It always writes both OBJ and
STL outputs under `remeshed/` unless `--output-root` is provided.

Use `--dry-run` to inspect the planned `vdb_tool` and Blender commands:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --dry-run
```

Remove enclosed internal void surfaces and normalize inverted normals during
OBJ-to-STL conversion. These are enabled by default:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision
```

Disable them explicitly:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --remove-internal-voids false \
    --fix-inverted-normals false
```

Keep the raw `vdb_tool` OBJ while still exporting a processed STL:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --sync-processed-obj false
```

Optionally apply conservative topology-based smoothing after cleanup and normal
fixing. This is disabled by default because thin sheets can still deform when
smoothing is too strong:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --smooth-mesh true \
    --smooth-repeat 2 \
    --smooth-lambda-factor 0.5
```

For thin parts, keep `--smooth-preserve-volume true` and start with
`--smooth-repeat 1` or `2` and `--smooth-lambda-factor 0.1` to `0.5`.
The current batch defaults are `--smooth-repeat 5`,
`--smooth-lambda-factor 0.6`, `--smooth-lambda-border 0.05`, and
`--smooth-preserve-volume true`, but smoothing is still off unless
`--smooth-mesh true` is supplied.

Optionally reduce face count after smoothing with Blender Decimate Collapse:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --smooth-mesh true \
    --decimate-mesh true \
    --decimate-ratio 0.5
```

Use `--decimate-max-faces` to cap the per-object face count:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --decimate-mesh true \
    --decimate-max-faces 5000
```

Blender's Decimate Collapse is approximate; the final face count may not match
the ratio exactly.

Current OpenVDB pass-through defaults:

```text
--remove-internal-voids true
--internal-void-volume-epsilon 1e-15
--fix-inverted-normals true
--normal-volume-epsilon 1e-15
--sync-processed-obj true
--decimate-mesh false
--decimate-ratio 0.5
--decimate-max-faces 0
```

The processing order is:

```text
source STL
  -> vdb_tool mesh2ls / close / ls2mesh
  -> intermediate OBJ
  -> Blender OBJ cleanup / normal fix
  -> optional smoothing
  -> optional decimation
  -> output STL
```

If `vdb_tool` is not on `PATH`, pass its absolute path:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --vdb-tool C:\path\to\vdb_tool.exe
```

If Blender is not on `PATH`, pass its absolute path:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision  \
    --blender D:\soft\blender4.3\blender.exe
```

### OpenVDB Quality Control

Higher detail uses smaller voxels and lower adaptivity, but produces heavier
meshes:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/remeshed_fine \
    --voxel 0.0005 \
    --width 23 \
    --close-radius 18 \
    --adapt 0.003
```

Lighter previews use larger voxels, stronger adaptivity, and optional decimate:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/remeshed_light \
    --voxel 0.002 \
    --adapt 0.02 \
    --decimate-mesh true \
    --decimate-max-faces 5000
```

If OpenVDB output looks faceted, add gentle smoothing after cleanup. For thin
parts, keep border smoothing low:

```bash
python scripts/src/collision_mesh_openvdb_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --smooth-mesh true \
    --smooth-repeat 2 \
    --smooth-lambda-factor 0.3 \
    --smooth-lambda-border 0.05 \
    --smooth-preserve-volume true
```

## Experimental: CoACD Merged Single STL

Script:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py <input>
```

This path is intended for comparison against the default Blender convex hull
and OpenVDB outputs. It runs:

```text
source mesh
  -> CoACD approximate convex decomposition
  -> concatenate convex hull parts
  -> joined STL / Manifold boolean union / Blender voxel remesh
  -> one STL
```

CoACD itself produces multiple convex hull parts. This script uses those parts
only as an intermediate segmented approximation, then writes one final STL with
the same file name under `coacd_merged/`.

Default run:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision
```

Default output:

```text
assets/robot/openarm_v2.0/meshes/arm/collision/
  link3.stl
  coacd_merged/
    link3.stl
    link3.coacd.json
```

The `.coacd.json` sidecar records the CoACD parameters, hull count, and basic
mesh statistics for later comparison.

Useful parameters:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --threshold 0.03 \
    --max-convex-hull 6 \
    --voxel-size 0.001
```

Guidance:

- Smaller `--threshold` usually creates more hulls and follows the source mesh
  more closely.
- `--max-convex-hull` caps the segmentation count when the output becomes too
  detailed.
- `--voxel-size` controls the final Blender wrapping/remesh resolution. Smaller
  values preserve more detail but produce heavier STLs.

More detailed CoACD fit with a bounded hull count and merge hulls with blender voxel:

```bash
.venv/bin/python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/coacd_detail \
    --threshold 0.02 \
    --max-convex-hull 32 \
    --resolution 4000 \
    --finalizer blender \
    --voxel-size 0.0008
```

Lighter CoACD comparison output without voxel remesh:

```bash
.venv/bin/python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/coacd_light \
    --threshold 0.06 \
    --max-convex-hull 3 \
    --finalizer joined \
    --keep-parts
```

Keep the intermediate CoACD hulls for inspection:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --keep-parts
```

Example with kept parts:

```text
assets/robot/openarm_v2.0/meshes/arm/collision/coacd_merged/
  link3.stl
  link3.coacd.json
  _parts/
    link3/
      link3_ch_000.stl
      link3_ch_001.stl
      ...
```

Run an explicit Blender Boolean union before voxel remesh:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --boolean-union
```

Boolean union is disabled by default because many overlapping hulls can produce
slow or fragile exact-boolean cases. Voxel remesh alone is usually the more
robust way to turn the concatenated hulls into one closed shell.

Use Manifold boolean union through trimesh:

```bash
.venv/bin/python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/coacd_manifold \
    --threshold 0.03 \
    --max-convex-hull 6 \
    --finalizer manifold
```

This keeps CoACD's segmented fit but avoids voxel remeshing. It is usually much
lighter than voxel remesh. The result is a true boolean union of touching or
overlapping hull volumes; if some hull groups do not touch, the STL can still
contain multiple closed components.

Use the lightweight joined finalizer:

```bash
.venv/bin/python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/coacd_joined \
    --threshold 0.03 \
    --max-convex-hull 6 \
    --finalizer joined
```

This is equivalent to the legacy `--skip-blender` option: it writes one STL file
containing all CoACD hull islands, without boolean union or remeshing.

### Fuse Existing CoACD Joined STLs

If mesh merging in `collision_mesh_coacd_merged_process.py` sometimes works not well, use `scripts/src/mesh_merge.py` to try more methods.

Turn on `--finalizer joined` and `--keep-parts` in `collision_mesh_coacd_merged_process.py` to directly disable mesh merging and keep all separate hulls.

Script:

```bash
.venv/bin/python scripts/src/mesh_merge.py <input> --output-root <output_dir>
```

Use this when a CoACD output already exists as one STL file containing multiple
closed hull islands and the hulls line up well at their contacts. The default
mode splits the islands, fixes component normals, and runs a
Manifold boolean union without voxel remeshing:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd/finger_outter.stl \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_fused \
    --mode manifold
```

Default output:

```text
assets/end_effector/pinch_gripper/meshes/collision/coacd_fused/
  finger_outter.stl
  finger_outter.mesh_merge.stl.json
```

If the CoACD hulls visually line up but Manifold leaves contact/internal faces,
use inflate-Manifold mode. It offsets each hull outward by a small distance,
runs Manifold union so near-contact hulls overlap, then optionally shrinks the
result back by the same distance:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd/finger_outter.stl \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_inflate_fused \
    --mode inflate-manifold \
    --inflate-distance 0.0002 \
    --shrink-after-inflate true
```

This is still not a voxel remesh; it keeps the mesh in the CoACD face-count
range while encouraging close hulls to become one unioned shell.

Optionally group only components whose vertices are close before unioning:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_fused \
    --mode manifold \
    --contact-tol 1e-5
```

There is also an experimental weld-only mode:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd/finger_outter.stl \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_welded \
    --mode weld \
    --weld-tol 1e-6
```

Weld mode is useful for inspection, but closed convex hulls can become
non-manifold if only some near-contact vertices are snapped together. For the
CoACD collision meshes, prefer the default Manifold mode first.

For a voxel-remeshed fallback on an existing joined STL, use the shared merge
tool's Blender mode:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd/finger_outter.stl \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_voxel_fused \
    --mode blender \
    --voxel-size 0.001 \
    --voxel-remesh true
```

If Blender is not on `PATH`, pass its absolute path:

```bash
python scripts/src/collision_mesh_coacd_merged_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --blender D:\soft\blender4.3\blender.exe
```

<!-- ## Experimental: trimesh / V-HACD Single STL

Script:

```bash
python scripts/src/collision_mesh_trimesh_vhacd_process.py <input>
```

This path uses:

```text
trimesh.decomposition.convex_decomposition()
```

In the current Python environment this is a wrapper around `vhacdx`, not CoACD.
It is useful as a second convex-decomposition baseline against CoACD.

Default run:

```bash
.venv/bin/python scripts/src/collision_mesh_trimesh_vhacd_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision
```

Default output:

```text
assets/robot/openarm_v2.0/meshes/arm/collision/
  link3.stl
  trimesh_vhacd/
    link3.stl
    link3.trimesh_vhacd.json
```

The default finalizer is `joined`, which concatenates all VHACD hulls into one
STL file without remeshing. This keeps the file small, but the output may
contain multiple closed mesh islands.

Useful parameters:

```bash
.venv/bin/python scripts/src/collision_mesh_trimesh_vhacd_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --max-convex-hulls 16 \
    --resolution 400000 \
    --max-num-vertices-per-ch 64 \
    --keep-parts
```

Use Manifold boolean union through trimesh:

```bash
.venv/bin/python scripts/src/collision_mesh_trimesh_vhacd_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/trimesh_vhacd_manifold \
    --finalizer manifold
```

This attempts to produce one real union mesh without voxel remeshing. It is
usually much lighter than voxel remesh, but can still fail if the hull set has
bad orientations or other boolean-unfriendly geometry.

Use the Blender helper as a finalizer:

```bash
.venv/bin/python scripts/src/collision_mesh_trimesh_vhacd_process.py \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/trimesh_vhacd_blender \
    --finalizer blender \
    --voxel-size 0.003
```

This is closest to the CoACD merged voxel-remesh path, but uses VHACD hulls as
the segmented approximation input. -->

## Directory Convention

Recommended layout:

```text
meshes/arm/collision/
  base_link.stl
  link1.stl
  link2.stl
  link3.stl
  link4.stl
  link5.stl
  link6.stl
  remeshed/
    base_link.obj
    base_link.stl
    link1.obj
    link1.stl
    ...
  coacd_merged/
    base_link.stl
    base_link.coacd.json
    link1.stl
    link1.coacd.json
    ...
  trimesh_vhacd/
    base_link.stl
    base_link.trimesh_vhacd.json
    link1.stl
    link1.trimesh_vhacd.json
    ...
```

Meaning:

- `collision/*.stl`: default collision mesh, generated by convex hull.
- `collision/remeshed/*.stl`: OpenVDB remeshed collision mesh.
- `collision/remeshed/*.obj`: intermediate OpenVDB mesh output kept for review.
- `collision/coacd_merged/*.stl`: experimental CoACD segmented fit, merged
  back into one STL with Blender voxel remesh.
- `collision/coacd_merged/*.coacd.json`: parameter and statistics sidecar for
  the CoACD merged result.
- `collision/trimesh_vhacd/*.stl`: experimental trimesh/V-HACD segmented fit,
  exported with the selected finalizer.
- `collision/trimesh_vhacd/*.trimesh_vhacd.json`: parameter and statistics
  sidecar for the trimesh/V-HACD result.
- `collision/source/*.stl`: source backups created only by convex hull `--replace`.

The OpenVDB script skips `remeshed/`, old `processed/`, and `source/` folders
when running recursively.
