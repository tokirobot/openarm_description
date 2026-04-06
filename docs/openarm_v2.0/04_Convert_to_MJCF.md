# Convert OpenArm v2.0 to MJCF

This document records the current conversion workflow from OpenArm v2.0 URDF
to MuJoCo MJCF XML.

The conversion is intentionally split into two stages:

```text
OpenArm assembled URDF
-> MuJoCo-friendly URDF bundle
-> MuJoCo MJCF XML
```

The first stage lives in `openarm_description` because it understands the
OpenArm description layout and processed mesh outputs. The second stage lives
in the MuJoCo model repository because it applies simulator-specific defaults,
actuators, contacts, material restoration, and mimic-joint equality constraints.

## 1. Repository Dependencies

Fill in the GitHub links for the repositories used by your workspace:

| Repository | Purpose | Link |
| --- | --- | --- |
| `openarm_description` | Source URDF, xacro, config, and mesh processing scripts | TODO: GitHub link |
| `openarm_v20_mujoco` | MJCF conversion scripts, default MuJoCo settings, and final XML models | TODO: GitHub link |

Example local paths used in this document:

```bash
export OPENARM_DESCRIPTION=home/<user>/ros2_ws/src/openarm_description
export OPENARM_MUJOCO=home/<user>/Documents/openarm_v20_mujoco
```

Adjust these paths for your own workspace.

## 2. Prerequisites

Generate or refresh the assembled URDF files first:

```bash
cd "$OPENARM_DESCRIPTION"
bash scripts/generate_urdfs.sh
```

The MuJoCo repository should provide a Python environment with the `mujoco`
package available. In the current workflow this is run through `uv`:

```bash
cd "$OPENARM_MUJOCO"
uv run python -c "import mujoco; print(mujoco.__version__)"
```

The visual mesh processing described in
`docs/openarm_v2.0/02_Visual_Mesh_Process.md` should already have produced
`*_mujoco_preview.xml` files for arm visual meshes. These preview files are used
to split visual DAE meshes into color-grouped OBJ visual meshes.

## 3. Stage 1: Prepare a MuJoCo-Friendly URDF

Script:

```text
scripts/src/prepare_mujoco_urdf.py
```

This script reads an assembled URDF and writes a self-contained conversion
bundle. It does several important MuJoCo-specific jobs:

- Adds a `<mujoco><compiler ... /></mujoco>` block to the URDF.
- Sets `discardvisual="false"` so MuJoCo keeps visual geoms.
- Sets `meshdir="meshes"` so mesh paths are resolved from the bundle's
  `meshes/` directory.
- Replaces unsplit visual DAE meshes with STL fallbacks when no color-split
  MuJoCo preview exists.
- Copies referenced meshes into a stable hierarchy:

```text
<output-dir>/
  <robot>.mujoco.urdf
  meshes/
    visual/*.obj
    visual/*.mtl
    visual/*.dae
    visual/*.stl
    collision/*.stl
```

The generated URDF stores mesh filenames relative to `meshdir`, for example:

```xml
<mujoco>
  <compiler discardvisual="false" meshdir="meshes" />
</mujoco>

<mesh filename="visual/link1_00.obj" />
<mesh filename="collision/link1.stl" />
```

### 3.1 Right Arm With Pinch Gripper

```bash
cd "$OPENARM_DESCRIPTION"

python scripts/src/prepare_mujoco_urdf.py \
  assets/robot/openarm_v2.0/urdf/example/openarm_right_arm_with_pinch_gripper.urdf \
  --output-dir "$OPENARM_MUJOCO/tmp/right_with_gripper" \
  --mujoco-meshdir meshes
```

Expected output:

```text
$OPENARM_MUJOCO/tmp/right_with_gripper/
  openarm_right_arm_with_pinch_gripper.mujoco.urdf
  meshes/
    visual/
    collision/
```

### 3.2 Default Bimanual

```bash
cd "$OPENARM_DESCRIPTION"

python scripts/src/prepare_mujoco_urdf.py \
  assets/robot/openarm_v2.0/urdf/example/openarm_default_bimanual.urdf \
  --output-dir "$OPENARM_MUJOCO/tmp/default_bimanual" \
  --mujoco-meshdir meshes
```

## 4. Stage 2: Convert the MuJoCo-Friendly URDF to MJCF

Script:

```text
$OPENARM_MUJOCO/scripts/convert_mujoco_urdf_to_xml.py
```

This script calls MuJoCo's URDF importer, saves the imported model as MJCF, and
then post-processes the generated XML.

The post-processing currently does the following:

- Restores URDF material names on visual geoms.
- Inserts default MuJoCo settings from `scripts/default_settings.xml`.
- Rewrites visual geoms as `class="visual"`.
- Rewrites collision geoms as `class="collision"`.
- Inserts actuator entries whose target joints exist in the generated model.
- Inserts contact excludes whose body or geom names exist in the generated
  model.
- Converts URDF `<mimic>` joints into MuJoCo `<equality><joint ... /></equality>`
  constraints.
- Preserves `compiler meshdir="meshes"` in the final MJCF.
- Rewrites MJCF asset mesh paths back to the stable hierarchy under
  `meshes/visual/` and `meshes/collision/`.
- Optionally sets MuJoCo `fusestatic="false"` before import so fixed URDF bodies
  such as `openarm_left_base_link` / `openarm_right_base_link` and their
  inertials are kept in the final MJCF.
- Optionally rotates `base_link_left/right_*` visual and collision geoms, plus
  preserved base-link inertials, by 180 degrees about local Y.

### 4.1 Right Arm With Pinch Gripper

```bash
cd "$OPENARM_MUJOCO"

uv run python scripts/convert_mujoco_urdf_to_xml.py \
  tmp/right_with_gripper/openarm_right_arm_with_pinch_gripper.mujoco.urdf \
  tmp/right_with_gripper/openarm_right_arm_with_pinch_gripper.xml
```

### 4.2 Default Bimanual

```bash
cd "$OPENARM_MUJOCO"

uv run python scripts/convert_mujoco_urdf_to_xml.py \
  tmp/default_bimanual/openarm_default_bimanual.mujoco.urdf \
  tmp/default_bimanual/openarm_default_bimanual.xml
```

### 4.3 Preserve and Rotate Base Links

Use this when the MJCF should keep the URDF base-link bodies and inertials
instead of letting MuJoCo fold fixed links into their parent body:

```bash
uv run python scripts/convert_mujoco_urdf_to_xml.py \
  tmp/default_bimanual/openarm_default_bimanual.mujoco.urdf \
  tmp/default_bimanual/openarm_default_bimanual.xml \
  --preserve-fixed-bodies
```

If the base-link meshes and inertials also need the 180 degree Y correction,
add:

```bash
uv run python scripts/convert_mujoco_urdf_to_xml.py \
  tmp/default_bimanual/openarm_default_bimanual.mujoco.urdf \
  tmp/default_bimanual/openarm_default_bimanual.xml \
  --preserve-fixed-bodies \
  --base-link-y180
```

`--base-link-y180` only matches `base_link_left_*` and `base_link_right_*`
geoms. It does not rotate the downstream arm link bodies or joints.

## 5. Why Temporary Mesh Aliases Are Needed

MuJoCo's URDF importer currently strips mesh subdirectories during import. For
example, a URDF mesh path such as:

```xml
<mesh filename="visual/link1_00.obj" />
```

may be looked up by MuJoCo as:

```text
meshes/link1_00.obj
```

For this reason, `convert_mujoco_urdf_to_xml.py` creates temporary basename
aliases under `meshdir` immediately before calling MuJoCo, then deletes them in
a `finally` block after conversion.

The permanent bundle remains clean:

```text
meshes/
  visual/...
  collision/...
```

If the converter prints:

```text
Temporary mesh basename aliases: 54 created, 3 reused
```

it means temporary compatibility files were created for MuJoCo's importer and
some entries were already directly reusable. This is informational, not an
error.

## 6. DAE Handling

MuJoCo may not be able to decode some visual DAE files directly.

The preferred handling happens in `prepare_mujoco_urdf.py`. If a visual DAE does
not have a color-split MuJoCo preview, the script looks for an STL fallback
before bundling:

1. Same directory, same stem as the DAE.
2. If that does not exist, an STL collision mesh on the same link.

Example:

```text
assets/robot/openarm_v2.0/meshes/body/visual/body_link0.dae
-> assets/robot/openarm_v2.0/meshes/body/visual/body_link0.stl
```

The bundled MuJoCo-friendly URDF then references the STL as a visual mesh:

```xml
<mesh filename="visual/body_link0.stl" />
```

If any DAE references still remain by the time `convert_mujoco_urdf_to_xml.py`
runs, the converter also tries a temporary STL fallback before calling MuJoCo.
This replacement is used only for MuJoCo import. The source URDF and source mesh
directories are not modified.

## 7. Validate the Generated MJCF

Load the generated XML with MuJoCo:

```bash
cd "$OPENARM_MUJOCO"

uv run python -c "\
import mujoco; \
m = mujoco.MjModel.from_xml_path('tmp/right_with_gripper/openarm_right_arm_with_pinch_gripper.xml'); \
print('loaded', 'nbody', m.nbody, 'nmesh', m.nmesh, 'ngeom', m.ngeom, 'nu', m.nu, 'neq', m.neq)"
```

Expected result for the right-arm-with-gripper test model is similar to:

```text
loaded nbody 10 nmesh 32 ngeom 35 nu 8 neq 1
```

Use the viewer if you want a visual check:

```bash
cd "$OPENARM_MUJOCO"
uv run mujoco_launch.py tmp/right_with_gripper/openarm_right_arm_with_pinch_gripper.xml
```

## 8. Troubleshooting

### Error: `Error opening file 'meshes/<mesh>.stl'`

MuJoCo stripped the subdirectory from a URDF mesh path. Use
`convert_mujoco_urdf_to_xml.py` rather than loading the prepared URDF directly,
because the converter creates temporary basename aliases before import.

Also check that mesh basenames are unique. If two different files share the same
basename, MuJoCo cannot disambiguate them after stripping directories.

### Error: `no decoder found for mesh file '<mesh>.dae'`

The MuJoCo importer could not decode a DAE file. Make sure a same-component STL
collision mesh exists under:

```text
meshes/collision/<mesh_stem>.stl
```

The converter will use that STL for import.

### Missing Actuators

Actuators from `scripts/default_settings.xml` are filtered by joint name. If an
actuator is missing in the final XML, check whether the generated MJCF contains
the referenced joint.

### Missing Contact Excludes

Contact excludes are filtered by body and geom names. If a contact exclude is
not copied, the referenced body or geom name was not present in the generated
MJCF.

## 9. Maintenance Notes

- Keep visual and collision mesh basenames unique when possible.
- Keep component directory names stable, because MJCF asset paths are rewritten
  back to these paths.
- Do not commit temporary conversion aliases under `meshes/`; they should be
  created and deleted by the converter.
- Update `scripts/default_settings.xml` when motor classes, position gains,
  contact excludes, or default collision/visual classes change.
- If a new gripper or end effector uses DAE visual meshes, provide STL collision
  meshes with matching component stems so the converter can fall back safely.
