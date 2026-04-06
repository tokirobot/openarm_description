# OpenArm v2.0 Description

This document explains the robot description design under `assets/robot/openarm_v2.0`.
It is written for two reading paths: first, a quick path that lets a new user
generate and preview a robot model quickly; then, a deeper path that explains
how the repository extracts reusable YAML configuration from source URDF / CAD
exports and assembles different OpenArm variants through preset-driven xacro.

## 1. What This Directory Solves

`openarm_v2.0` uses a data-driven URDF generation pipeline:

```text
source URDF / CAD export
-> extract reusable YAML configs
-> assemble robot variants from robot_presets
-> generate URDF through one xacro entry
-> preview in RViz or use in downstream tools
```

The main reasons for this structure are:

- Arm, body, and end-effector geometry, inertia, joint, and reference-point data
  live in editable YAML files.
- Robot assembly decisions live in `config/robot_presets/*.yaml`, so each robot
  variant does not need its own copied xacro tree.
- Users can copy a preset, edit a few fields, and generate a new single-arm,
  dual-arm, gripper, or no-gripper URDF.
- xacro is responsible for reading configuration, validating presets, resolving
  mount points, applying mirroring, collapsing internal empty links, and emitting
  optional grasp helper frames.

## 2. Quick Start

### 2.1 Build and Source the Workspace

The current xacro files still use `$(find openarm_description)` for package path
resolution, so the ROS 2 workspace must be built at least once.

```bash
cd ~/ros2_ws
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash
```

After changing xacro files, launch files, RViz configs, meshes, or packaged
configuration resources, rebuild and source the workspace again before relying
on ROS 2 launch or installed package paths.

### 2.2 Generate the Default Dual-Arm URDF

```bash
cd ~/ros2_ws/src/openarm_description
bash scripts/generate_urdfs.sh
```

The default run generates:

- `assets/robot/openarm_v2.0/urdf/build/openarm_default_bimanual.urdf`
- `assets/robot/openarm_v2.0/urdf/build/openarm_default_bimanual_grasp.urdf`

### 2.3 Preview in RViz

```bash
ros2 launch openarm_description display_openarm.launch.py
```

Preview a single right arm with a pinch gripper:

```bash
ros2 launch openarm_description display_openarm.launch.py \
  robot_preset:=right_arm_with_pinch_gripper \
  rviz_config:=arm_only.rviz
```

Preview a model with grasp helper frames:

```bash
ros2 launch openarm_description display_openarm.launch.py \
  robot_preset:=default_bimanual \
  emit_grasp_frame:=true
```

### 2.3 Preview in VS Code with the URDF Visualizer Extension

Install the [URDF Visualizer extension](https://marketplace.visualstudio.com/items?itemName=morningfrog.urdf-visualizer), then add the package mapping below to your workspace `.vscode/settings.json`.

If VS Code is opened at the `openarm_description` package root, use:

```json
{
  "urdf-visualizer.packages": {
    "openarm_description": "${workspaceFolder}"
  }
}
```

If VS Code is opened at the ROS 2 workspace root, use:

```json
{
  "urdf-visualizer.packages": {
    "openarm_description": "${workspaceFolder}/src/openarm_description"
  }
}
```

This mapping lets the extension resolve `package://openarm_description/...` mesh paths in generated URDF files. If a preset depends on an external description package such as `zed_description`, add that package to the same map as well.

## 3. Preset Preview

These images show representative outputs generated from the current presets.
They are small previews only; use RViz or a URDF viewer for detailed inspection.

| Right arm with pinch gripper | Left arm with pinch gripper |
| --- | --- |
| <img src="imgs/openarm_v2.0_right_arm_with_pinch_gripper.png" alt="Right arm with pinch gripper" width="150"> | <img src="imgs/openarm_v2.0_left_arm_with_pinch_gripper.png" alt="Left arm with pinch gripper" width="150"> |

| Default bimanual | Bimanual with grasp frame |
| --- | --- |
| <img src="imgs/openarm_v2.0_bimanual.png" alt="Default bimanual" width="150"> | <img src="imgs/openarm_v2.0_bimanual_with_grasp_frame.png" alt="Bimanual with grasp frame" width="150"> |

## 4. Assets Layout

```text
assets/
|-- robot/
|   `-- openarm_v2.0/
|       |-- config/
|       |-- imgs/
|       |-- meshes/
|       `-- urdf/
|-- end_effector/
|   `-- pinch_gripper/
|       |-- config/
|       |-- meshes/
|       `-- urdf/
`-- sensor/
    `-- zed/
        `-- urdf_wrapper/
```

Main responsibilities:

| Path | Purpose |
| --- | --- |
| `assets/robot/openarm_v2.0/config/` | Robot presets plus OpenArm body and arm YAML configs |
| `assets/robot/openarm_v2.0/meshes/` | OpenArm body and arm visual / collision meshes |
| `assets/robot/openarm_v2.0/imgs/` | Documentation preview images |
| `assets/robot/openarm_v2.0/urdf/` | The public v2.0 xacro entry point and assembly utilities |
| `assets/end_effector/<product>/` | Reusable end-effector configs, meshes, and optional standalone xacro |
| `assets/sensor/<product>/` | Sensor wrappers or local sensor assets |

The preset schema still uses semantic types such as `robot`, `end_effector`,
and `sensor`. Those types map to the matching directories under `assets/`.
For example, `type: sensor` and `product: zed` resolves to:

```text
assets/sensor/zed/
```

This keeps all mesh, image, config, and wrapper resources in one package asset
root while preserving clear product labels such as `openarm_v2.0`.

## 5. Core Entry Point

The public entry point is:

```text
assets/robot/openarm_v2.0/urdf/openarm_v20.urdf.xacro
```

It exposes three arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `robot_preset` | `default_bimanual` | Selects `config/robot_presets/<name>.yaml` |
| `collapse_internal_empty_links` | `true` | Collapses internal empty links between the arm and EE when possible |
| `emit_grasp_frame` | `false` | Emits grasp helper frames for supported end effectors |

Direct xacro example:

```bash
xacro assets/robot/openarm_v2.0/urdf/openarm_v20.urdf.xacro \
  robot_preset:=right_arm_with_pinch_gripper \
  emit_grasp_frame:=true \
  > assets/robot/openarm_v2.0/urdf/build/openarm_right_arm_with_pinch_gripper_grasp.urdf
```

For day-to-day use, prefer the wrapper script:

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper --grasp-frame
```

For the full script interface, see:

```text
docs/openarm_v2.0/01_URDF_Extract_Scripts.md
```

## 6. What a Preset Is

`config/robot_presets/*.yaml` files describe robot assembly variants. They do
not store mesh or inertia values directly. Instead, they tell xacro:

- What the root frame is called.
- Which components are enabled.
- Whether each component comes from `robot`, `end_effector`, or `sensor`.
- Which product and config payload each component should use.
- Which inertial config each component should use.
- What link and joint name prefix to apply to each component.
- Which parent component each child component attaches to.
- Which reference point should be used for alignment.
- Whether a component should be mirrored.
- Whether gripper fingers should be swapped.
- Whether any joint limits should be overridden.

A preset usually starts like this:

```yaml
robot:
  root_frame: world
  components:
    - body
    - primary_arm
    - secondary_arm
    - primary_arm_end_effector
    - secondary_arm_end_effector
```

`robot.components` defines the component scan order. xacro starts from the
single enabled root component and recursively emits attached children.

## 7. Preset Field Reference

| Field | Applies to | Meaning |
| --- | --- | --- |
| `type` | all | Top-level component source. Currently supported: `robot`, `end_effector`, `sensor` |
| `enabled` | all | Whether the component participates in this URDF generation |
| `product` | all | Product directory under `assets/<type>/`, for example `openarm_v2.0`, `pinch_gripper`, or `zed` |
| `config` | all | String for an internal config/member, `null` when the product has no extra index, or an object passed to a wrapper |
| `inertials` | robot / end_effector | Selects `inertials/<name>.yaml`; currently `nominal` is the common value |
| `prefix` | robot / end_effector / sensor | Prefix for emitted link and joint names, for example `openarm_left_` |
| `link_name` | robot body | Renames the emitted body link; body currently has one link |
| `connection.attach_to` | child component | Selects the parent component |
| `connection.parent_reference_point` | child component | Uses a reference point on the parent component as the mount point |
| `connection.parent` | all | Explicit parent link override; overrides the link inferred from a reference point |
| `connection.origin` | all | Explicit mount origin override; can override fields inferred from a reference point |
| `reflect.x/y/z` | all | Mirror axes; only one axis may currently be set to `-1` |
| `reflect.include` | all | Limits mirroring to specific links, joints, and reference points |
| `limit_override_joints` | arm / end_effector | Overrides selected joint limits |
| `swap_fingers` | end_effector | Swaps finger source links and mimic mapping for mirrored two-finger grippers |

Each component chooses its own inertial file through `inertials`. For example,
`inertials: nominal` loads `inertials/nominal.yaml` from that component's config
package. If you add another file such as `inertials/cad_refresh.yaml`, you can
switch only the desired component in the preset:

```yaml
primary_arm:
  type: robot
  product: openarm_v2.0
  config: arm
  inertials: cad_refresh
```

`config` is interpreted by its shape:

| Shape | Meaning |
| --- | --- |
| string | Load an internal config/member, for example `body` or `arm` |
| `null` | Use the product root config directly |
| object | Pass wrapper parameters through, for example ZED camera arguments |

## 8. Asset Config Structure

### 8.1 Arm Config

```text
config/arm/
|-- struct/
|   |-- topology.yaml
|   |-- name_mapping.yaml
|   `-- reference_points.yaml
|-- joint/
|   |-- joint_origins.yaml
|   |-- joint_axes.yaml
|   |-- joint_limits.yaml
|   `-- joint_mimics.yaml
|-- link/
|   |-- visuals.yaml
|   `-- collisions.yaml
|-- inertials/
|   `-- nominal.yaml
`-- control/
    |-- control_gains.yaml
    `-- friction.yaml
```

xacro mainly reads:

- `struct/topology.yaml`: link and joint tree structure.
- `struct/reference_points.yaml`: assembly reference points such as
  `ee_mount_point`.
- `joint/joint_origins.yaml`: joint origins.
- `joint/joint_axes.yaml`: joint axes.
- `joint/joint_limits.yaml`: joint limits.
- `link/visuals.yaml`: visual mesh, scale, and origin data.
- `link/collisions.yaml`: collision mesh, scale, and origin data.
- `inertials/nominal.yaml`: mass, inertia, and inertial origin data.

The parameters under `control/` are currently not part of the main URDF assembly
path. They are reserved for control-side or later integration work.

### 8.2 Body Config

The body is currently a single-link component. Its main files are:

- `struct/topology.yaml`
- `struct/reference_points.yaml`
- `link/visuals.yaml`
- `link/collisions.yaml`
- `inertials/nominal.yaml`

Body reference points are used to mount the left and right arms, for example:

- `left_arm_mount_point`
- `right_arm_mount_point`

### 8.3 End-Effector Config

For `pinch_gripper`, the structure is:

```text
assets/end_effector/pinch_gripper/config/
|-- struct/
|   |-- topology.yaml
|   |-- name_mapping.yaml
|   `-- reference_points.yaml
|-- joint/
|   |-- joint_origins.yaml
|   |-- joint_axes.yaml
|   |-- joint_limits.yaml
|   `-- joint_mimics.yaml
|-- link/
|   |-- visuals.yaml
|   `-- collisions.yaml
`-- inertials/
    `-- nominal.yaml
```

The `grasp_frame` entry in `reference_points.yaml` is emitted as a helper link
when `emit_grasp_frame:=true`.

### 8.4 Sensor Products

Sensors are attached through thin OpenArm wrappers around external description
packages. The first supported product is `zed`, which uses the
`zed_description` package from `zed-ros2-description`.

The wrapper is:

```text
assets/sensor/zed/urdf_wrapper/openarm_zed_wrapper.xacro
```

It includes:

```text
$(find zed_description)/urdf/zed_macro.urdf.xacro
```

and calls `xacro:zed_camera`. OpenArm only adds the fixed mount joint from the
chosen parent link or reference point to `${sensor_name}_camera_link`.

Example:

```yaml
head_zed:
  type: sensor
  enabled: true
  product: zed
  config:
    camera_name: openarm_head_zed
    camera_model: zed2i
    custom_baseline: 0.0
    enable_gnss: false
  prefix: openarm_head_
  connection:
    attach_to: body
    parent_reference_point: zed_front_mount_point
    parent: null
    origin: null
  reflect:
    x: 1
    y: 1
    z: 1
```

The example preset `example_default_bimanual_with_zed.yaml` shows a body-mounted
ZED camera. Its `zed_front_mount_point` pose is intentionally easy to tune from
CAD or calibration.

## 9. Assembly Algorithm Overview

The v2.0 xacro assembly logic can be understood as five steps:

```text
load preset
-> validate preset
-> load component descriptors
-> resolve runtime assembly data
-> emit body / arm / end_effector recursively
```

### 9.1 Load the Preset

`openarm_v20.urdf.xacro` reads:

```text
config/robot_presets/<name>.yaml
```

from:

```text
robot_preset:=<name>
```

It then passes the parsed YAML data to `openarm_v20_robot`.

### 9.2 Validate the Preset

xacro validates the preset before emitting URDF content:

- `robot.components` must not be empty.
- The enabled components must contain exactly one root component.
- `components` must not contain duplicate component names.
- Every component listed in `components` must be defined in the YAML file.
- `attach_to` must point to an existing, enabled parent component that is also
  listed in `robot.components`.
- `attach_to` must not create an attachment cycle.
- `type` must be one of `body`, `arm`, or `end_effector`.
- `reflect.x/y/z` must each be either `1` or `-1`.
- Only single-axis reflection is currently supported.

These checks make preset mistakes fail early instead of producing a malformed
URDF that is difficult to debug.

### 9.3 Load Component Descriptors

Each component is normalized into a descriptor. A descriptor contains:

- component name
- component type
- config root
- prefix / link prefix
- actual root link name
- topology
- reference points
- joint origins / axes / limits / mimics
- inertials
- visuals
- collisions
- default mount parent
- whether terminal empty-link collapse is supported

Body, arm, end-effector, and sensor components come from different source
directories or packages, but the assembly stage uses a unified descriptor shape.

### 9.4 Resolve Runtime Assembly Data

Runtime resolution converts the preset's assembly intent into concrete URDF
output parameters:

- Which parent link the current component attaches to.
- What the mount origin is.
- Whether a parent reference point is used.
- Whether `connection.parent` or `connection.origin` overrides the default
  result.
- Which mirror axis is active.
- Which links, joints, and reference points participate in mirroring.
- Which joint limits are overridden.
- Whether the EE needs `swap_fingers`.
- Whether a terminal empty link should be collapsed.

Mount resolution can be read as this priority order:

1. If `attach_to` and `parent_reference_point` are set, infer the parent link and
   origin from the parent component's reference point.
2. If `connection.parent` is set, use it to override the inferred parent link.
3. If `connection.origin` is set, use it to override the corresponding origin
   fields.
4. If no reference point or override is provided, use the default parent and a
   zero origin.

`connection.origin` supports partial overrides: any field left as `null` keeps
the value that was already resolved from the reference point or default origin.

### 9.5 Recursively Emit the Component Tree

xacro starts at the single enabled root component:

```text
root_frame
-> root component
-> attached children
-> children's attached children
```

Each component is dispatched by type:

- `body` calls the body emitter.
- `arm` calls the arm emitter.
- `end_effector` calls the EE emitter.
- `sensor` calls the sensor product wrapper.

## 10. Mirroring Rules

`reflect` allows one source configuration to generate left and right side
components. For example, a right-side arm can be mirrored into a left-side arm by
setting `y: -1`.

Example:

```yaml
reflect:
  x: 1
  y: -1
  z: 1
  include:
    links: [base_link, link1, link2, link5, link6, link7]
    joints: [joint1, joint2, joint3, joint5, joint6, joint7]
    reference_points: [ee_mount_point]
```

Current limits:

- Only single-axis mirroring is supported.
- `x/y/z` must be either `1` or `-1`.
- If `include` is set, only the listed links, joints, and reference points are
  mirrored.

Mirroring affects:

- mesh scale sign
- origin translation
- joint axis sign
- joint limit sign range
- inertia cross terms such as `ixy`, `ixz`, and `iyz`

## 11. Reference Points and Mounting

`reference_points.yaml` describes predefined assembly or helper points inside a
component. A reference point is not an actual moving joint; it is a coordinate
reference used for assembly or semantic marking.

Arm tip example:

```yaml
ee_mount_point:
  parent: link7
  origin:
    x: 0.0205
    y: 0
    z: 0
    roll: 0
    pitch: 0
    yaw: 0
```

A gripper can attach to the arm like this:

```yaml
primary_arm_end_effector:
  type: end_effector
  enabled: true
  product: pinch_gripper
  prefix: openarm_left_
  connection:
    attach_to: primary_arm
    parent_reference_point: ee_mount_point
    parent: null
    origin: null
```

This means:

- `primary_arm_end_effector` attaches to `primary_arm`.
- It uses `primary_arm`'s `ee_mount_point` as the mount pose.
- It does not manually override the parent link.
- It does not manually override the origin.

If the mount orientation or position must be changed, override
`connection.origin`. The override may be partial: set only the fields that need
to change and leave the remaining fields as `null` to keep the reference-point
or default values.

This lets a component define reusable interface positions internally. It also
lets the arm define a reference frame for the final active joint and the future
child mount without requiring the child component to be assembled in CAD first.

## 12. Empty-Link Collapse

`collapse_internal_empty_links` defaults to `true`. It handles internal empty
links around the arm-to-EE connection. These helper frames are typically created
so independent component development can define the arm-side joint frame and
mount pose before the arm and EE are fully assembled together.

When all of the following conditions are true, xacro collapses the parent
component's terminal empty link:

- The parent component supports tip collapse; currently this mainly means arm
  components.
- The parent's terminal link has no inertial, visual, or collision data.
- The child component attaches to that terminal link through
  `parent_reference_point`.
- The child component does not explicitly set `connection.parent`.
- No multiple children compete for the same terminal empty link.

Here, "terminal link" means the final canonical link in the parent component's
`topology.links` list, for example `link7` in the arm config. It does not mean
the original source-URDF child helper link that was converted into a
`reference_points.yaml` entry during extraction.

After collapse, the child component base frame absorbs the original mount
transform, and the generated URDF is simpler.

To keep these internal empty links, generate a no-collapse variant:

```bash
bash scripts/generate_urdfs.sh --keep-empty-links
```

Or call xacro directly:

```bash
xacro assets/robot/openarm_v2.0/urdf/openarm_v20.urdf.xacro \
  robot_preset:=default_bimanual \
  collapse_internal_empty_links:=false \
  > /urdf/openarm_default_bimanual_no_collapse.urdf
```

## 13. Grasp Frame

`emit_grasp_frame` defaults to `false`. When enabled, supported end effectors
read `grasp_frame` from their own `reference_points.yaml` and emit it as a fixed
helper link. This `grasp_frame` is the nominal reference pose for grasping an
object with the gripper.

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper --grasp-frame
```

Notes:

- If a preset does not enable an end effector, `--grasp-frame` will not add an
  actual grasp frame.
- If the end-effector config does not define a `grasp_frame` reference point, no
  helper frame is emitted.
- The current `pinch_gripper` supports `grasp_frame`.

## 14. Pinch Gripper

The current `openarm_v20_ee.xacro` mainly targets a two-finger gripper topology:

```text
base_link
|-- joint1 -> link1
`-- joint2 -> link2
```

It additionally handles:

- `ee_` link name prefixing.
- finger link emission.
- finger joint emission.
- mimic joint remapping.
- `swap_fingers`.
- mirrored joint limits.
- optional `grasp_frame`.

The left-side gripper usually needs:

```yaml
reflect:
  x: 1
  y: -1
  z: 1
swap_fingers: true
```

The right-side gripper usually uses:

```yaml
reflect:
  x: 1
  y: 1
  z: 1
swap_fingers: false
```

## 15. Common Generation Commands

Generate the default dual-arm model:

```bash
bash scripts/generate_urdfs.sh
```

Generate all presets:

```bash
bash scripts/generate_urdfs.sh --all
```

Generate one preset:

```bash
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper
```

Generate the grasp-frame variant for one preset:

```bash
bash scripts/generate_urdfs.sh \
  --preset right_arm_with_pinch_gripper \
  --grasp-frame
```

Generate no-collapse variants:

```bash
bash scripts/generate_urdfs.sh --keep-empty-links
```

Generate all presets as no-collapse grasp-frame variants:

```bash
bash scripts/generate_urdfs.sh --all --keep-empty-links --grasp-frame
```

The output directory is:

```text
assets/robot/openarm_v2.0/urdf/build/
```

## 16. Adding a Robot Variant

The recommended workflow is to copy an existing preset.

For example, start from the right arm with pinch gripper:

```bash
cp assets/robot/openarm_v2.0/config/robot_presets/right_arm_with_pinch_gripper.yaml \
   assets/robot/openarm_v2.0/config/robot_presets/my_right_arm.yaml
```

Then edit:

- `robot.components`
- component `enabled` flags
- `prefix`
- `connection`
- `reflect`
- `limit_override_joints`
- `swap_fingers`

Generate the new variant:

```bash
bash scripts/generate_urdfs.sh --preset my_right_arm
```

If xacro reports a preset validation error, check:

- whether `robot.components` references an undefined component
- whether enabled components contain exactly one root component
- whether `attach_to` points to an enabled parent component
- whether `reflect` uses only one `-1` axis
- whether `parent_reference_point` exists in the parent component's
  `reference_points.yaml`

## 17. Refreshing Configs from Source URDF

The extraction logic is implemented in:

```text
scripts/src/extract_urdf_params.py
```

It can extract the following from a URDF:

- topology
- reference points
- joint origins
- joint axes
- joint limits
- joint mimics
- inertials
- visuals
- collisions
- meshes

For normal use, prefer the wrapper:

```bash
bash scripts/dev_extract.sh \
  test \
  --source <package-style name or full URDF file path> \
  --target arm_test \
  --inertials-name nominal
```

After checking the test output, release it:

```bash
bash scripts/dev_extract.sh \
  release \
  --source <package-style name or full URDF file path> \
  --target arm \
  --inertials-name nominal \
  --existing overwrite
```

To extract an arm and EE together:

```bash
bash scripts/dev_extract_arm_with_ee.sh \
  test \
  --arm-source <package-style name or full URDF file path> \
  --ee-source <package-style name or full URDF file path> \
  --arm-target arm_ee_test \
  --inertials-name nominal
```

The wrappers default to `--inertials-name nominal`, which writes
`inertials/nominal.yaml`. If you want to keep multiple inertial variants, pass a
different name such as `--inertials-name cad_refresh`.

For the complete script interface, see:

```text
docs/openarm_v2.0/01_URDF_Extract_Scripts.md
```

## 18. Validation Checklist

After changing configuration or xacro, run at least the following checks.

### 18.1 Confirm xacro Generation

```bash
bash scripts/generate_urdfs.sh --preset default_bimanual
```

### 18.2 Confirm RViz Display

```bash
ros2 launch openarm_description display_openarm.launch.py \
  robot_preset:=default_bimanual
```

### 18.3 Check Single-Arm and Gripper Variants

```bash
bash scripts/generate_urdfs.sh --preset right_arm
bash scripts/generate_urdfs.sh --preset left_arm
bash scripts/generate_urdfs.sh --preset right_arm_with_pinch_gripper --grasp-frame
bash scripts/generate_urdfs.sh --preset left_arm_with_pinch_gripper --grasp-frame
```

### 18.4 Check No-Collapse Variants

```bash
bash scripts/generate_urdfs.sh --preset default_bimanual --keep-empty-links
```

If `check_urdf` is installed, use it to inspect generated URDF structure as
well.

## 19. Troubleshooting

### `$(find openarm_description)` Cannot Find the Package

The workspace is usually not built or sourced:

```bash
cd ~/ros2_ws
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash
```

### Meshes Do Not Appear in RViz

Check:

- whether the package was rebuilt after resource changes
- whether mesh URIs use `package://openarm_description/...`
- whether the mesh files exist under `meshes/visual` or `meshes/collision`
- whether RViz is using the intended preset and config

### `--grasp-frame` Does Not Add a Grasp Frame

Check:

- whether the preset enables an end effector
- whether the end-effector `reference_points.yaml` contains `grasp_frame`
- whether `emit_grasp_frame` is set to `true`

### Preset Validation Fails

Common causes:

- `robot.components` contains duplicate components.
- `robot.components` references components that are not defined in YAML.
- A child component attaches to a disabled parent component.
- More than one enabled component is acting as a root component.
- `reflect.x/y/z` contains more than one `-1`.
- `parent_reference_point` does not exist in the parent component config.

### Left / Right Mirroring Looks Wrong

Check:

- whether `reflect` sets `-1` only on the intended axis
- whether `reflect.include.links` contains links that need mirroring
- whether `reflect.include.joints` contains joints that need mirroring
- whether `reflect.include.reference_points` contains mount points that need
  mirroring
- whether the gripper needs `swap_fingers`

## 20. Current Limitations

- v2.0 is currently a description pipeline, not a full control, simulation, or
  planning pipeline.
- Mirroring currently supports only one reflected axis.
- `openarm_v20_ee.xacro` currently mainly targets the two-finger pinch gripper.
- `collapse_internal_empty_links` mainly targets the arm terminal empty-link to
  EE base connection case.
- `control/` parameters are not yet part of the main URDF assembly path.
- `assets/robot/openarm_v1.0` is the legacy compatibility path. New work should prefer
  `assets/robot/openarm_v2.0`.

## 21. Recommended Maintenance Rules

- Add robot variants by adding presets first; avoid copying the whole xacro tree.
- Modify YAML first when changing geometry, inertia, joint, or reference-point
  parameters.
- Modify `urdf/utils/*.xacro` only when assembly rules need to change.
- Add a new end effector as an independent `assets/end_effector/<product>/config`
  and mesh package.
- After modifying source URDF, refresh configs through the extraction scripts
  and compare test output before release.
- After changing presets, generate at least default bimanual, left arm, right
  arm, left arm with gripper, and right arm with gripper variants.

## 22. Future Work

- Support more source types or user-defined products beyond `robot`,
  `end_effector`, and `sensor`.
- Extract a more general component emitter, especially for the shared parts of　body and arm emission, so new component classes can be supported with less　duplicated xacro logic.
- Support more complex mirroring and reference-frame transformations.
- Generalize end-effector definitions beyond the current two-finger pinch
  gripper-specific emitter.

<!--
Potential later split:

- `docs/openarm_v2.0/README.md`: quick start, core concepts, common commands.
- `docs/openarm_v2.0/architecture.md`: xacro assembly algorithm, preset validation,
  mirroring, and collapse.
- `docs/openarm_v2.0/preset_schema.md`: preset field reference and examples.
- `docs/openarm_v2.0/extraction.md`: source URDF to YAML extraction workflow.
- `docs/openarm_v2.0/troubleshooting.md`: common errors and debugging.
-->
