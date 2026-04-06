# Mesh Tools

This document describes the standalone mesh utility scripts under
`scripts/src/`. They are intentionally small entry points around one task each:

- `mesh_decimate.py`: reduce STL/OBJ face count.
- `mesh_merge.py`: merge multiple STL/OBJ files, or fuse a single joined STL.
- `mesh_repair.py`: repair STL/OBJ geometry.
- `mesh_smooth.py`: smooth STL/OBJ geometry.

Use these tools for local mesh cleanup experiments before feeding meshes into
the visual, collision, OpenVDB, CoACD, or MJCF flows.

## Requirements

The Blender-based tools must be run through Blender:

```bash
blender --background --python scripts/src/mesh_decimate.py -- <args>
blender --background --python scripts/src/mesh_repair.py -- <args>
blender --background --python scripts/src/mesh_smooth.py -- <args>
```

The merge tool is a normal Python script:

```bash
.venv/bin/python scripts/src/mesh_merge.py <args>
```

Python dependencies:

```bash
.venv/bin/python -m pip install trimesh manifold3d networkx
```

`manifold3d` is only required for `mesh_merge.py --mode manifold`.
`networkx` is used by `trimesh` graph/component operations such as splitting
mesh islands before merge.

If Blender is not on `PATH`, replace `blender` with its absolute path, or pass
`--blender` to `mesh_merge.py --mode blender`.

## Decimate STL/OBJ

Script:

```text
scripts/src/mesh_decimate.py
```

This tool imports one mesh or a directory of STL/OBJ meshes, applies Blender
Decimate Collapse, and exports STL or OBJ. It is the standalone version of the
decimate step that was previously embedded in `blender_obj_to_stl.py`.

Reduce faces by ratio:

```bash
blender --background --python scripts/src/mesh_decimate.py -- \
    input.stl \
    output_decimated.stl \
    --ratio 0.5
```

Cap per-object face count:

```bash
blender --background --python scripts/src/mesh_decimate.py -- \
    input.stl \
    output_decimated.stl \
    --max-faces 5000
```

Use both when needed:

```bash
blender --background --python scripts/src/mesh_decimate.py -- \
    input.obj \
    output_decimated.stl \
    --ratio 0.8 \
    --max-faces 8000 \
    --triangulate
```

Batch a directory into a separate output root:

```bash
blender --background --python scripts/src/mesh_decimate.py -- \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    assets/robot/openarm_v2.0/meshes/arm/collision_decimated \
    --ratio 0.5 \
    --extensions stl
```

Batch recursively and preserve the relative folder layout:

```bash
blender --background --python scripts/src/mesh_decimate.py -- \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    assets/robot/openarm_v2.0/meshes/arm/collision_decimated \
    --recursive \
    --extensions stl,obj \
    --max-faces 5000 \
    --triangulate
```

Notes:

- `--ratio` is clamped to `[0.01, 1.0]`.
- `--max-faces` is applied per imported mesh object.
- In directory mode, the second positional argument is the output root. The
  output keeps each input mesh's relative path and extension.
- `--recursive` only affects directory input.
- Blender Decimate is approximate; the final face count may not equal the cap
  exactly.

## Merge STL/OBJ

Script:

```text
scripts/src/mesh_merge.py
```

This tool supports six modes:

- `joined`: concatenate mesh geometry into one file. This does not remove
  internal/contact faces and does not create a true boolean union.
- `manifold`: split components, then run `trimesh.boolean.union` with the
  Manifold engine.
- `inflate-manifold`: offset each component outward, run Manifold union, then
  optionally shrink the result back by the same distance.
- `weld`: snap nearby vertices and remove degenerate/duplicate faces without
  boolean union.
- `blender`: split components, write temporary STL parts, then call
  `blender_coacd_union_remesh.py` for join/Boolean/voxel remesh.
- `split`: split connected components and export each component as its own
  STL/OBJ for inspection.

### Join Multiple Files

Use this for a lightweight single STL that still contains separate mesh
islands:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    part_a.stl part_b.obj part_c.stl \
    --output joined.stl \
    --mode joined
```

### Fuse Multiple Files With Manifold

Use this when the parts are watertight volumes that touch or overlap and a true
boolean union is desired:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    part_a.stl part_b.stl part_c.stl \
    --output fused.stl \
    --mode manifold
```

By default `--check-volume false` is used because convex decomposition outputs
are expected to be closed volumes. Enable it for stricter validation:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    part_a.stl part_b.stl \
    --output fused.stl \
    --mode manifold \
    --check-volume true
```

### Fuse One Joined STL

Use this when one STL already contains many closed islands, such as a joined
CoACD output:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_hulls.stl \
    --output joined_hulls_fused.stl \
    --mode manifold \
    --split-components true
```

`--split-components true` is the default. It makes `mesh_merge.py` treat each
connected component inside the single STL as an individual union input.
For Manifold modes, non-watertight or near-zero-volume split components are
reported and skipped before boolean union. This avoids tiny triangle artifacts
causing an empty or invalid boolean result.

### Export Connected Components

Use split mode to inspect which islands are present inside one STL:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_or_raw.stl \
    --output joined_or_raw_components \
    --mode split
```

The output path is a directory in `--mode split`. Component files are named like
`<stem>_component_00.stl`, and a JSON manifest in the same directory records
vertex count, face count, watertight status, Euler number, volume, and bounds.

Use `--component-format obj` if OBJ output is preferred:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_or_raw.stl \
    --output joined_or_raw_components_obj \
    --mode split \
    --component-format obj
```

For batch splitting, use `--output-root`; each input mesh gets a matching
subdirectory:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/robot/openarm_v2.0/meshes/arm/collision/coarse \
    --output-root assets/robot/openarm_v2.0/meshes/arm/collision/coarse_components \
    --mode split
```

Optionally group only components whose vertices are close before unioning:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_hulls.stl \
    --output joined_hulls_contact_fused.stl \
    --mode manifold \
    --contact-tol 1e-5
```

The Manifold modes fix component normals by default before unioning. Disable
this only when the source orientation is intentional:

```bash
--fix-component-normals false
```

### Inflate Manifold Fuse

Use this when the hulls visually line up but Manifold leaves contact/internal
faces because the components only nearly touch:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_hulls.stl \
    --output joined_hulls_inflate_fused.stl \
    --mode inflate-manifold \
    --inflate-distance 0.0002 \
    --shrink-after-inflate true
```

This is still not a voxel remesh; it keeps the mesh close to the original hull
face-count range while encouraging close hulls to become one unioned shell.

### Weld Only

Use weld mode for inspection or for meshes that only need near-duplicate
vertices snapped together:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_hulls.stl \
    --output joined_hulls_welded.stl \
    --mode weld \
    --weld-tol 1e-6 \
    --duplicate-faces keep-first
```

Weld mode is not a boolean union. Closed convex hulls can become non-manifold if
only some near-contact vertices are snapped together.

### Batch Directory Fuse

Use `--output-root` instead of `--output` to process each mesh in a folder into
the matching relative output path:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    assets/end_effector/pinch_gripper/meshes/collision/coacd \
    --output-root assets/end_effector/pinch_gripper/meshes/collision/coacd_fused \
    --mode manifold \
    --contact-tol 1e-5
```

Use `--dry-run` to print the planned per-file jobs without loading or writing
meshes.

### Blender Join / Voxel Remesh

Use Blender mode when Manifold fails, when hulls nearly touch but do not
overlap, or when a voxelized wrapped result is acceptable:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    joined_hulls.stl \
    --output joined_hulls_voxel.stl \
    --mode blender \
    --voxel-remesh true \
    --voxel-size 0.001
```

Ask Blender to run explicit Boolean union before voxel remesh:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    part_a.stl part_b.stl \
    --output blender_boolean_voxel.stl \
    --mode blender \
    --boolean-union \
    --boolean-solver EXACT \
    --voxel-remesh true
```

Boolean union can be slower and less robust than voxel remesh alone for many
overlapping convex hulls.

The merge tool writes a JSON sidecar by default:

```text
joined_hulls_fused.mesh_merge.stl.json
```

Disable it with:

```bash
--manifest false
```

## Repair STL/OBJ

Script:

```text
scripts/src/mesh_repair.py
```

This tool imports one STL/OBJ or a directory of STL/OBJ meshes, cleans
loose/degenerate geometry, fills boundary holes, removes internal void islands
with opposite signed volume, fixes remaining inverted-normal islands, and
exports STL or OBJ.

Default repair:

```bash
blender --background --python scripts/src/mesh_repair.py -- \
    input.stl \
    repaired.stl
```

More explicit repair:

```bash
blender --background --python scripts/src/mesh_repair.py -- \
    input.obj \
    repaired.stl \
    --merge-distance 1e-6 \
    --fill-holes true \
    --hole-sides 0 \
    --remove-internal-voids true \
    --fix-inverted-normals true \
    --recalculate-normals true \
    --shade-smooth \
    --check-self-intersections true \
    --triangulate
```

Normal-only correction, useful after merge/CoACD inspection when the geometry
should not be healed or simplified:

```bash
blender --background --python scripts/src/mesh_repair.py -- \
    input.stl \
    normal_fixed.stl \
    --normal-only
```

Batch repair a directory:

```bash
blender --background --python scripts/src/mesh_repair.py -- \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    assets/robot/openarm_v2.0/meshes/arm/collision_repaired \
    --recursive \
    --extensions stl,obj \
    --remove-internal-voids true \
    --fix-inverted-normals true
```

Important options:

- `--merge-distance`: welds vertices closer than this distance. Start small,
  for example `1e-7` to `1e-5` in meter-scale meshes.
- `--fill-holes true`: closes boundary loops. `--hole-sides 0` allows all loop
  sizes; use a positive number to limit hole filling to smaller holes.
- `--remove-internal-voids true`: separates loose islands and deletes islands
  whose signed volume is opposite the largest-volume reference shell.
- `--fix-inverted-normals true`: flips remaining negative-volume shells.
- `--recalculate-normals true`: runs Blender normal consistency repair before
  export.
- `--normal-only`: only flips negative-volume shells and recalculates normals;
  it disables loose/degenerate cleanup, hole filling, vertex merging, and
  internal void removal.
- `--shade-smooth`: changes display normals for smoother visual appearance; it
  does not change geometry.
- `--check-self-intersections true`: reports non-adjacent triangle
  intersections after repair. This catches closed but self-intersecting meshes
  that still pass watertight/boundary checks.
- `--fail-on-self-intersections true`: exits with an error if self-intersections
  are found, and does not export the repaired mesh.

This repair step is conservative. It can remove enclosed loose void shells and
close broken boundary loops, but it is not a full CAD healing system. Inspect
thin shells, intentionally hollow meshes, and reported self-intersections before
replacing source assets. Automatic self-intersection repair generally requires
remeshing or local manual cleanup, both of which can change feature shape.

## Smooth STL/OBJ

Script:

```text
scripts/src/mesh_smooth.py
```

This tool applies topology-based vertex smoothing to one STL/OBJ or a directory
of STL/OBJ meshes. It is the standalone version of the smoothing step that was
previously embedded in `blender_obj_to_stl.py`.

Conservative smoothing:

```bash
blender --background --python scripts/src/mesh_smooth.py -- \
    input.stl \
    smoothed.stl \
    --repeat 1 \
    --lambda-factor 0.3 \
    --preserve-volume true
```

Stronger smoothing:

```bash
blender --background --python scripts/src/mesh_smooth.py -- \
    input.stl \
    smoothed.stl \
    --repeat 3 \
    --lambda-factor 0.5 \
    --lambda-border 0.2 \
    --preserve-volume true \
    --triangulate
```

Batch smooth a directory:

```bash
blender --background --python scripts/src/mesh_smooth.py -- \
    assets/robot/openarm_v2.0/meshes/arm/collision \
    assets/robot/openarm_v2.0/meshes/arm/collision_smoothed \
    --recursive \
    --extensions stl,obj \
    --repeat 1 \
    --lambda-factor 0.3 \
    --preserve-volume true
```

Guidance:

- Start with `--repeat 1` or `2`.
- Keep `--preserve-volume true` for closed collision meshes.
- Reduce `--lambda-border` on open surfaces to avoid pulling boundary edges too
  aggressively.
- `--shade-smooth` changes normals for display; it does not change geometry.

## Typical Workflows

Repair, then decimate:

```bash
blender --background --python scripts/src/mesh_repair.py -- \
    raw.stl repaired.stl \
    --merge-distance 1e-6

blender --background --python scripts/src/mesh_decimate.py -- \
    repaired.stl repaired_decimated.stl \
    --max-faces 5000
```

Join parts, then smooth and decimate:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    part_a.stl part_b.stl part_c.stl \
    --output joined.stl \
    --mode joined

blender --background --python scripts/src/mesh_smooth.py -- \
    joined.stl joined_smoothed.stl \
    --repeat 1 \
    --lambda-factor 0.2

blender --background --python scripts/src/mesh_decimate.py -- \
    joined_smoothed.stl joined_smoothed_decimated.stl \
    --max-faces 8000
```

Fuse a joined CoACD-style STL without voxel remesh:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    coacd_joined.stl \
    --output coacd_manifold_fused.stl \
    --mode manifold \
    --split-components true
```

Fuse a joined STL with Blender voxel remesh:

```bash
.venv/bin/python scripts/src/mesh_merge.py \
    coacd_joined.stl \
    --output coacd_voxel_fused.stl \
    --mode blender \
    --voxel-size 0.001
```
