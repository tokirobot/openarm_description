# OpenArm v1.0 Compatibility

This directory is kept as a **minimal compatibility layer** for the old `v1.0` robot description.

It is intentionally narrow in scope:

- only `arm_type:=v10` is supported
- only `body_type:=v10` is supported
- only the legacy `parallel_link` end effector is supported
- newer hardware variants should use [OpenArm v2.0 description](../openarm_v2.0/00_OpenArm_v2.0_Description.md)

## Purpose

This compatibility layer exists so that old `v10`-style URDF/xacro entry points can still generate a valid robot description without affecting the newer preset-driven `v2.0` pipeline.

It is **not** the active development target.

## Directory Layout

```text
assets/robot/openarm_v1.0/
├── config/
│   ├── arm/
│   └── body/
├── mesh/
│   ├── arm/
│   └── body/
├── urdf/
│   ├── arm/
│   ├── body/
│   ├── ee/
│   ├── robot/
│   └── ros2_control/
└── README.md
```

The old `v1.0` entry reuses:

- `assets/robot/openarm_v1.0/config/*`
- `assets/robot/openarm_v1.0/mesh/*`
- `assets/end_effector/parallel_link/*`

## Main Entry

The main compatibility entry is:

```text
assets/robot/openarm_v1.0/urdf/robot/openarm_robot.urdf.xacro
```

Supported arguments include:

- `arm_type` with required value `v10`
- `body_type` with required value `v10`
- `bimanual`
- `ros2_control`
- `left_arm_prefix`
- `right_arm_prefix`
- `left_arm_base_xyz`
- `right_arm_base_xyz`
- `left_arm_base_rpy`
- `right_arm_base_rpy`

If `arm_type` or `body_type` is set to anything other than `v10`, the xacro will fail on purpose and direct you to `assets/robot/openarm_v2.0`.

## Generate URDF

### Prerequisite

Because the xacro files use `$(find openarm_description)`, build the workspace first:

```bash
cd /home/li/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash
```

### Single Arm

Generate the legacy single-arm `v10` robot:

```bash
xacro assets/robot/openarm_v1.0/urdf/robot/openarm_robot.urdf.xacro \
  arm_type:=v10 \
  body_type:=v10 \
  bimanual:=false \
  > /tmp/openarm_v10_single.urdf
```

### Bimanual

Generate the legacy bimanual `v10` robot:

```bash
xacro assets/robot/openarm_v1.0/urdf/robot/openarm_robot.urdf.xacro \
  arm_type:=v10 \
  body_type:=v10 \
  bimanual:=true \
  > /tmp/openarm_v10_bimanual.urdf
```

## Parallel Link End Effector

The old `v1.0` robot path uses the legacy `parallel_link` gripper.

A standalone helper entry is also available:

```text
assets/end_effector/parallel_link/urdf/parallel_link_standalone.urdf.xacro
```

Generate it directly with:

```bash
xacro assets/end_effector/parallel_link/urdf/parallel_link_standalone.urdf.xacro \
  ee_config_dir:=/home/li/ros2_ws/src/openarm_description/assets/end_effector/parallel_link/config \
  mesh_root:=/home/li/ros2_ws/src/openarm_description/assets/end_effector/parallel_link/mesh \
  > /tmp/parallel_link.urdf
```

## Notes

- `assets/robot/openarm_v1.0` is compatibility-only
- `assets/robot/openarm_v2.0` is the active, maintained robot description system
- if you need presets, modular assembly, or current end-effector workflows, use `v2.0`
