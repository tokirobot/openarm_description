# Scripts Guide

This document explains the purpose, workflows, inputs, outputs, and maintenance
patterns for the scripts under `scripts/`. Its scope is intentionally different
from `docs/openarm_v2.0/00_OpenArm_v2.0_Description.md`:

- `docs/openarm_v2.0/00_OpenArm_v2.0_Description.md` explains the overall description pipeline,
  preset-driven xacro architecture, assembly rules, and core concepts.
- This document explains how to operate the script layer: how to extract YAML
  configs from source URDFs, how meshes are copied, how assembled URDFs are
  generated, and what each script writes.

## 1. What the Scripts Directory Solves

`scripts/` is responsible for two main jobs:

```text
source URDF / CAD export
-> extract YAML config package and meshes
-> use configs from robot_presets
-> generate assembled URDFs
```

More specifically:

- `scripts/src/extract_urdf_params.py` is the low-level extractor. It reads URDF
  files and writes YAML config packages.
- `scripts/dev_extract.sh` is the single-component extraction wrapper. It is
  useful for extracting arm, body-style, or end-effector configs.
- `scripts/dev_extract_arm_with_ee.sh` is the paired extraction wrapper. It is
  useful when extracting an arm and end effector together.
- `scripts/generate_urdfs.sh` is the URDF generation wrapper. It generates
  assembled URDFs from existing configs and `robot_presets`.

## 2. Which Script Should I Use?

| Goal | Recommended script |
| --- | --- |
| Generate URDFs from existing presets | `scripts/generate_urdfs.sh` |
| Extract one component config from one source URDF | `scripts/dev_extract.sh` |
| Extract arm and EE configs from two source URDFs | `scripts/dev_extract_arm_with_ee.sh` |
| Refresh only inertials | `scripts/dev_extract.sh --inertials-only` or `scripts/dev_extract_arm_with_ee.sh --inertials-only` |
| Refresh inertials into a custom file such as `inertials/cad_refresh.yaml` | `scripts/dev_extract.sh --inertials-name cad_refresh` |
| Need include / exclude / filter / subtree controls | `scripts/src/extract_urdf_params.py` |

For normal development, prefer the bash wrappers. Call the Python extractor
directly only when the wrapper interface is not enough.

## 3. Source URDF Input Rules

The extraction wrappers accept two source formats:

1. A full URDF file path.
2. A package-style short name such as `openarm_v2.0_no_gripper`.

If a short name is provided, the script expands it to:

```text
assets/robot/openarm_v2.0/base_urdf_ws/urdf_paks/<name>/urdf/<name>.urdf
```

For example:

```bash
--source openarm_v2.0_no_gripper
```

resolves to:

```text
assets/robot/openarm_v2.0/base_urdf_ws/urdf_paks/openarm_v2.0_no_gripper/urdf/openarm_v2.0_no_gripper.urdf
```

Note: these source URDF packages may not exist in the repository by default. If
you use a short name, place the corresponding source package under
`assets/robot/openarm_v2.0/base_urdf_ws/urdf_paks/` first.

## 4. Test Mode and Release Mode

The extraction wrappers support:

- `test`
- `release`

### 4.1 Test Mode

`test` mode is for safe trial runs. It does not write into the official config
or mesh directories.

Single-component extraction writes to:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<target>/config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<target>/meshes/
```

Paired arm + EE extraction writes to:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<arm-target>/arm_config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<arm-target>/arm_meshes/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<arm-target>/ee_config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/<arm-target>/ee_meshes/
```

For any new source URDF, run `test` first and inspect the output before using
`release`.

### 4.2 Release Mode

`release` mode writes into the official project directories.

Normal component output:

```text
assets/robot/openarm_v2.0/config/<target>/
assets/robot/openarm_v2.0/meshes/<target>/
```

End-effector output:

```text
assets/end_effector/<target>/config/
assets/end_effector/<target>/meshes/
```

Important: `release` only creates or refreshes config and mesh packages. It does
not automatically edit `robot_presets/*.yaml`. To use a released config in robot
assembly, manually update the preset's `config` or `product` field.

## 5. Existing-File Policy

The wrappers expose two existing-file policies:

| Argument | Meaning |
| --- | --- |
| `--existing skip` | Skip existing config / mesh / inertial files |
| `--existing overwrite` | Overwrite existing config / mesh / inertial files |

The current wrapper default is:

```text
--existing skip
```

Recommendations:

- Use the default `skip` policy for early test runs.
- Before releasing into official directories, confirm that the test output is
  correct.
- Before using `--existing overwrite`, check your git diff or backup state so
  important parameters are not overwritten unintentionally.

The low-level Python extractor has more granular policies:

- `--existing-config {prompt,overwrite,skip}`
- `--existing-mesh {prompt,overwrite,skip}`
- `--existing-inertials {prompt,overwrite,skip,number}`

The wrappers intentionally simplify these into one `--existing` option.

## 6. Common Workflows

### 6.1 Test-Extract an Arm Config

```bash
bash scripts/dev_extract.sh \
  test \
  --source <package-style name or full URDF file path> \
  --target arm_test \
  --inertials-name nominal
```

Output:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_test/config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_test/meshes/
```

### 6.2 Release an Arm Config

```bash
bash scripts/dev_extract.sh \
  release \
  --source <package-style name or full URDF file path> \
  --target arm \
  --inertials-name nominal \
  --existing overwrite
```

Output:

```text
assets/robot/openarm_v2.0/config/arm/
assets/robot/openarm_v2.0/meshes/arm/
```

After release, generate a default preset to verify:

```bash
bash scripts/generate_urdfs.sh --preset default_bimanual
```

### 6.3 Test-Extract an End Effector

```bash
bash scripts/dev_extract.sh \
  test \
  --source <package-style name or full URDF file path> \
  --target ee_test \
  --inertials-name nominal \
  --ee
```

Output:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/ee_test/config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/ee_test/meshes/
```

### 6.4 Release an End Effector

```bash
bash scripts/dev_extract.sh \
  release \
  --source <package-style name or full URDF file path> \
  --target pinch_gripper \
  --inertials-name nominal \
  --ee \
  --existing overwrite
```

Output:

```text
assets/end_effector/pinch_gripper/config/
assets/end_effector/pinch_gripper/meshes/
```

After release, verify with a gripper preset:

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper --grasp-frame
```

### 6.5 Test-Extract Arm and EE Together

```bash
bash scripts/dev_extract_arm_with_ee.sh \
  test \
  --arm-source <package-style name or full URDF file path> \
  --ee-source <package-style name or full URDF file path> \
  --arm-target arm_ee_test \
  --inertials-name nominal
```

Output:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_ee_test/arm_config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_ee_test/arm_meshes/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_ee_test/ee_config/
assets/robot/openarm_v2.0/base_urdf_ws/extracted/arm_ee_test/ee_meshes/
```

### 6.6 Release Arm and EE Together

```bash
bash scripts/dev_extract_arm_with_ee.sh \
  release \
  --arm-source <package-style name or full URDF file path> \
  --ee-source <package-style name or full URDF file path> \
  --arm-target arm \
  --ee-target pinch_gripper \
  --inertials-name nominal \
  --existing overwrite
```

Output:

```text
assets/robot/openarm_v2.0/config/arm/
assets/robot/openarm_v2.0/meshes/arm/
assets/end_effector/pinch_gripper/config/
assets/end_effector/pinch_gripper/meshes/
```

### 6.7 Refresh Only Inertials

Single component:

```bash
bash scripts/dev_extract.sh \
  test \
  --source <package-style name or full URDF file path> \
  --target arm_test \
  --inertials-only \
  --inertials-name cad_refresh
```

Arm + EE:

```bash
bash scripts/dev_extract_arm_with_ee.sh \
  test \
  --arm-source <package-style name or full URDF file path> \
  --ee-source <package-style name or full URDF file path> \
  --arm-target arm_ee_test \
  --inertials-only \
  --inertials-name cad_refresh
```

`--inertials-only` writes inertials only and does not copy meshes. The wrapper
still defaults to `--inertials-name nominal`, but you can redirect the output to
another file such as `inertials/cad_refresh.yaml`.

### 6.8 Generate the Default Assembled URDFs

```bash
bash scripts/generate_urdfs.sh
```

Default output:

```text
urdf/openarm_default_bimanual.urdf
urdf/openarm_default_bimanual_grasp.urdf
```

### 6.9 Generate All Presets

```bash
bash scripts/generate_urdfs.sh --all
```

### 6.10 Generate One Preset

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper
```

### 6.11 Generate a Grasp-Frame Variant

```bash
bash scripts/generate_urdfs.sh \
  --preset right_arm_with_pinch_gripper \
  --grasp-frame
```

### 6.12 Generate a No-Collapse Variant

```bash
bash scripts/generate_urdfs.sh \
  --preset default_bimanual \
  --keep-empty-links
```

## 7. Script Reference

### 7.1 `scripts/dev_extract.sh`

Purpose:

- Extract one config package from one source URDF.
- Can be used for arm or body-style configs.
- With `--ee`, writes into the end-effector directory structure.

Usage:

```bash
bash scripts/dev_extract.sh \
  [test|release] \
  --source <package-style name or full URDF file path> \
  --target <target_name> \
  [--ee] \
  [--inertials-only] \
  [--inertials-name <name>] \
  [--existing overwrite|skip]
```

Required arguments:

| Argument | Meaning |
| --- | --- |
| `test|release` | Write to test output or official output; default is `test` |
| `--source` | Source URDF path or package-style short name |
| `--target` | Output target name |

Optional arguments:

| Argument | Meaning |
| --- | --- |
| `--ee` | Switch release output to `assets/end_effector/<target>/` |
| `--inertials-only` | Extract inertials only and skip mesh copying |
| `--inertials-name <name>` | Write inertials to `inertials/<name>.yaml`; default is `nominal` |
| `--existing overwrite|skip` | Existing-file policy; default is `skip` |

Output path rules:

| Mode | `--ee` | Output |
| --- | --- | --- |
| `test` | no | `assets/robot/openarm_v2.0/base_urdf_ws/extracted/<target>/config` |
| `test` | yes | `assets/robot/openarm_v2.0/base_urdf_ws/extracted/<target>/config` |
| `release` | no | `assets/robot/openarm_v2.0/config/<target>` |
| `release` | yes | `assets/end_effector/<target>/config` |

### 7.2 `scripts/dev_extract_arm_with_ee.sh`

Purpose:

- Extract arm and EE configs from two source URDFs in one workflow.
- Useful when refreshing arm and gripper configs from a paired CAD / URDF export.

Usage:

```bash
bash scripts/dev_extract_arm_with_ee.sh \
  [test|release] \
  --arm-source <package-style name or full URDF file path> \
  --ee-source <package-style name or full URDF file path> \
  --arm-target <arm_target_or_test_name> \
  [--ee-target <ee_target_name_if_release>] \
  [--inertials-only] \
  [--inertials-name <name>] \
  [--existing overwrite|skip]
```

Required arguments:

| Argument | Meaning |
| --- | --- |
| `test|release` | Write to test output or official output; default is `test` |
| `--arm-source` | Arm source URDF path or package-style short name |
| `--ee-source` | EE source URDF path or package-style short name |
| `--arm-target` | Test directory name in test mode; arm config name in release mode |

Extra required argument in release mode:

| Argument | Meaning |
| --- | --- |
| `--ee-target` | End-effector product name, for example `pinch_gripper` |

Optional arguments:

| Argument | Meaning |
| --- | --- |
| `--inertials-only` | Extract inertials only for both arm and EE |
| `--inertials-name <name>` | Write both outputs to `inertials/<name>.yaml`; default is `nominal` |
| `--existing overwrite|skip` | Existing-file policy; default is `skip` |

Output path rules:

| Mode | Output |
| --- | --- |
| `test` | `base_urdf_ws/extracted/<arm-target>/arm_config` and `ee_config` |
| `release` | `assets/robot/openarm_v2.0/config/<arm-target>` and `assets/end_effector/<ee-target>/config` |

### 7.3 `scripts/generate_urdfs.sh`

Purpose:

- Generate assembled URDFs from existing config packages and `robot_presets`.
- Does not extract parameters or modify YAML files.

Usage:

```bash
bash scripts/generate_urdfs.sh \
  [--preset <preset_name>] \
  [--all] \
  [--grasp-frame] \
  [--keep-empty-links]
```

Arguments:

| Argument | Meaning |
| --- | --- |
| `--preset <name>` | Generate only the selected preset |
| `--all` | Generate every real preset under `config/robot_presets/`, skipping `example_*` |
| `--grasp-frame` | Generate only the grasp-frame variant |
| `--keep-empty-links` | Set `collapse_internal_empty_links:=false` and generate no-collapse variants |

Default behavior:

- With no arguments, only `default_bimanual` is generated.
- The default run generates both standard and `_grasp` variants.
- Output is written to `assets/robot/openarm_v2.0/urdf/build/`.

Single-preset behavior:

- `--preset <name>` generates only the standard collapsed variant.
- `--preset <name> --grasp-frame` generates only the grasp variant.

Output naming rules:

| Option | Filename suffix |
| --- | --- |
| default collapsed | no extra suffix |
| `--grasp-frame` | `_grasp` |
| `--keep-empty-links` | `_no_collapse` |
| both | `_no_collapse_grasp` |

## 8. Python Extractor Reference

`scripts/src/extract_urdf_params.py` is the low-level extractor. The wrappers
eventually call this script.

Call it directly when:

- you need include / exclude link or joint controls
- you need a custom output layout
- you need split / subtree export
- you need separate existing-file policies for configs, meshes, and inertials
- you are debugging the extractor itself

### 8.1 Basic Example

```bash
python3 scripts/src/extract_urdf_params.py \
  --urdf /path/to/model.urdf \
  --output-dir /tmp/model_extract \
  --configs-layout tree \
  --inertials-name nominal \
  --mesh-copy-to /tmp/model_extract/meshes \
  --mesh-prefix package://openarm_description/tmp/model_extract/meshes
```

### 8.2 Exported Files

Full export mode can write:

- `struct/topology.yaml`
- `struct/name_mapping.yaml`
- `struct/reference_points.yaml`
- `joint/joint_origins.yaml`
- `joint/joint_axes.yaml`
- `joint/joint_limits.yaml`
- `joint/joint_mimics.yaml`
- `link/visuals.yaml`
- `link/collisions.yaml`
- `inertials/<name>.yaml`

### 8.3 Output Layout

`--configs-layout tree` outputs:

```text
<output>/
├── struct/
│   ├── topology.yaml
│   ├── name_mapping.yaml
│   └── reference_points.yaml
├── joint/
│   ├── joint_origins.yaml
│   ├── joint_axes.yaml
│   ├── joint_limits.yaml
│   └── joint_mimics.yaml
├── link/
│   ├── visuals.yaml
│   └── collisions.yaml
└── inertials/
    └── nominal.yaml
```

`--configs-layout flat` writes the same files directly under the output
directory. Use `tree` for official project configs and `flat` for quick
inspection.

### 8.4 Output Path Arguments

| Argument | Meaning |
| --- | --- |
| `--output-dir` | Output root directory |
| `--output-folder` | Optional subdirectory appended under `--output-dir` |

Example:

```bash
--output-dir assets/robot/openarm_v2.0/base_urdf_ws/extracted
--output-folder smoke_test
```

Result:

```text
assets/robot/openarm_v2.0/base_urdf_ws/extracted/smoke_test/
```

### 8.5 Mesh Arguments

| Argument | Meaning |
| --- | --- |
| `--mesh-prefix` | Rewrites mesh URIs inside exported YAML |
| `--mesh-copy-to` | Copies source meshes into a filesystem directory |

Example:

```bash
--mesh-prefix package://openarm_description/assets/robot/openarm_v2.0/meshes/arm
--mesh-copy-to assets/robot/openarm_v2.0/meshes/arm
```

This writes mesh URIs such as:

```text
package://openarm_description/assets/robot/openarm_v2.0/meshes/arm/visual/<file>
package://openarm_description/assets/robot/openarm_v2.0/meshes/arm/collision/<file>
```

and copies meshes into:

```text
assets/robot/openarm_v2.0/meshes/arm/visual/
assets/robot/openarm_v2.0/meshes/arm/collision/
```

You can use only `--mesh-prefix`, only `--mesh-copy-to`, or both together.

### 8.6 Inertials Arguments

| Argument | Meaning |
| --- | --- |
| `--inertials-name` | Controls the `inertials/<name>.yaml` filename |
| `--content all` | Exports the full config package |
| `--content inertials` | Exports inertials only |

Example:

```bash
--inertials-name nominal
```

writes:

```text
inertials/nominal.yaml
```

### 8.7 Filtering Arguments

For partial extraction:

| Argument | Meaning |
| --- | --- |
| `--include-links` | Keep only the listed links, comma-separated |
| `--exclude-links` | Exclude listed links after inclusion, comma-separated |
| `--include-joints` | Keep only the listed joints, comma-separated |
| `--exclude-joints` | Exclude listed joints after inclusion, comma-separated |
| `--root-link` | Select traversal root when the filtered graph is ambiguous |

### 8.8 Reference Points

The extractor detects terminal empty-link reference frames and writes them to:

```text
struct/reference_points.yaml
```

Typical examples:

- arm-side EE mounting point
- gripper-side grasp frame
- virtual reference point created by split / subtree export

For the current arm source, the expected result is:

- `joint7` remains in topology.
- `ee_mount_point` is written to `struct/reference_points.yaml`.

Reference points are assembly or semantic reference frames. They are not primary
functional joints in the moving topology.

Their `meta` block is descriptive metadata only. The current OpenArm assembly
pipeline does not consume `meta.kind`; extracted reference points now use
`meta.note` to explain how the boundary was detected.

### 8.9 Split / Subtree Export

The extractor can split a subtree after a selected joint.

Main arguments:

| Argument | Meaning |
| --- | --- |
| `--truncate-at-joint` | Selects the boundary joint |
| `--save-subtree` | Saves the separated subtree |
| `--split-reference-mode create_virtual` | Keeps the selected split joint in the primary topology, then creates a virtual fixed boundary on the split joint child frame; default and recommended for non-fixed split joints |
| `--split-reference-mode use_joint` | Uses the selected fixed joint itself as the split boundary, so the primary export stops before that joint |

In practice:

- `create_virtual` keeps the selected split joint in the primary topology.
- The generated split reference is attached to the split joint child frame with
  an identity origin.
- This behaves like inserting a virtual fixed boundary immediately after the
  selected split joint.
- `use_joint` requires a fixed split joint and places the split reference at the
  selected joint origin on the parent side.

Recommendation:

- Prefer extracting arm and end effector as separate source packages whenever
  the source URDFs are already separable.
- Treat `create_virtual` as a compatibility path for cases where arm and
  gripper are still developed as one combined robot and you do not want to
  complicate the source model yet.
- Outside that compatibility case, prefer a clean split workflow instead of
  relying on virtual split boundaries.

Subtree output arguments mirror the main output interface:

- `--subtree-output-dir`
- `--subtree-output-folder`
- `--subtree-configs-layout`
- `--subtree-inertials-name`
- `--subtree-content`
- `--subtree-mesh-prefix`
- `--subtree-mesh-copy-to`

If `--subtree-output-dir` is not set, subtree output defaults to:

```text
<primary-output>_subtree
```

## 9. How to Validate Results

### 9.1 Check YAML Completeness

Confirm that the output directory contains:

```text
struct/topology.yaml
struct/reference_points.yaml
joint/joint_origins.yaml
joint/joint_axes.yaml
joint/joint_limits.yaml
link/visuals.yaml
link/collisions.yaml
inertials/nominal.yaml
```

For end effectors, also check:

```text
joint/joint_mimics.yaml
```

If the model should emit a grasp frame later, check:

```text
struct/reference_points.yaml
```

for:

```text
grasp_frame
```

### 9.2 Check Mesh URIs

Confirm that `link/visuals.yaml` and `link/collisions.yaml` point to the intended
mesh locations, for example:

```text
package://openarm_description/assets/robot/openarm_v2.0/meshes/arm/visual/<file>
```

Also confirm that the matching mesh files exist on disk.

### 9.3 Generate URDFs

```bash
bash scripts/generate_urdfs.sh --preset default_bimanual
```

Or inspect a specific preset:

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper --grasp-frame
```

### 9.4 Check in RViz

```bash
ros2 launch openarm_description display_openarm.launch.py \
  robot_preset:=default_bimanual
```

## 10. Troubleshooting

### Source URDF Not Found

Check:

- whether `--source` is a full path
- if using a short name, whether the file exists at
  `assets/robot/openarm_v2.0/base_urdf_ws/urdf_paks/<name>/urdf/<name>.urdf`

### `package://` Mesh URI Cannot Be Resolved

The extractor resolves `package://` URIs from nearby package candidates in the
source URDF parent chain. If the URI cannot be resolved from that context, the
extractor fails.

Recommendations:

- Confirm that the source URDF package structure is complete.
- Confirm that mesh paths really exist in the source package.
- If needed, use a full URDF path while preserving the original package
  directory structure.

### Presets Do Not Change After Release

This is expected. `release` writes config and mesh files only. It does not edit
`robot_presets/*.yaml`.

If you added:

```text
assets/robot/openarm_v2.0/config/my_arm
```

then update the component in the preset:

```yaml
config: my_arm
```

If you added:

```text
assets/end_effector/my_gripper
```

then update the EE component in the preset:

```yaml
product: my_gripper
```

### Files Were Not Overwritten

The default policy is:

```text
--existing skip
```

If you intentionally want to overwrite:

```bash
--existing overwrite
```

### `--grasp-frame` Does Not Emit a Grasp Frame

Check:

- whether the preset enables an end effector
- whether the EE `struct/reference_points.yaml` contains `grasp_frame`
- whether `--grasp-frame` or `emit_grasp_frame:=true` is enabled

### URDF Generation Cannot Find `openarm_description`

Build and source the workspace:

```bash
cd ~/ros2_ws
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash
```

## 11. Maintenance Recommendations

- Run new source URDFs in `test` mode before release.
- Check git diff before release, especially before overwriting official
  parameters.
- After release, generate at least one related preset and preview it in RViz.
- After adding a config package, update `robot_presets/*.yaml` accordingly.
- Use `scripts/src/extract_urdf_params.py` directly for extraction needs that the
  wrappers do not expose.
- If wrapper arguments keep growing, consider whether the new capability should
  remain in the Python extractor instead of making the bash wrapper more complex.
