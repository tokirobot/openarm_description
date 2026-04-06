# Environment Setup

This document describes the environment needed by the OpenArm v2.0 description
and mesh-processing tools.

The recommended setup is:

```text
ROS 2 workspace
+ openarm_description
+ system Blender 4.3.2 on PATH
+ local Python virtual environment at openarm_description/.venv
+ OpenVDB vdb_tool when using the OpenVDB collision workflow
```

## 0. Clone Openarm Description 

Assuming you are working with ROS2 and your path to ROS2 workspace is:

```bash
ls ~/ros2_ws
```

Or you can create your ROS2 workspace:

```bash
mkdir ~/ros2_ws/src
```

Clone openarm description to your workspace:
```bash
cd ~/ros2_ws/src # or your own workspace
git clone TODO: <openarm description>
```

## 1. System Packages

Install the common build, Python, ROS, and mesh-tool prerequisites:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  curl \
  git \
  python3 \
  python3-pip \
  python3-venv \
  python3-colcon-common-extensions \
  python3-rosdep
```

Install the ROS packages used by `package.xml`:

```bash
sudo apt install -y \
  ros-${ROS_DISTRO}-xacro \
  ros-${ROS_DISTRO}-robot-state-publisher \
  ros-${ROS_DISTRO}-joint-state-publisher \
  ros-${ROS_DISTRO}-joint-state-publisher-gui \
  ros-${ROS_DISTRO}-rviz2 \
  ros-${ROS_DISTRO}-ros-gz
```

`zed_description` is also declared as a dependency. Install it from the ROS
package repository if available for your distro, or clone/build the ZED ROS 2
description package in the same workspace.

Then resolve anything still missing:

```bash
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
```

## 2. Blender 4.3.2

The visual workflow, convex-hull collision workflow, and standalone
`mesh_decimate.py`, `mesh_repair.py`, and `mesh_smooth.py` tools run inside
Blender. Use Blender 4.3.2 for reproducible results with the current scripts.

### 2.1 Linux Tarball Install

Download the official Blender 4.3.2 Linux tarball and install it under a fixed tools directory:

```bash
cd /tmp
curl -LO https://download.blender.org/release/Blender4.3/blender-4.3.2-linux-x64.tar.xz
mkdir -p "$HOME/tools"
tar -xf blender-4.3.2-linux-x64.tar.xz -C "$HOME/tools"
```

Add it to `PATH`:

```bash
cat >> "$HOME/.bashrc" <<'EOF'

# Blender for OpenArm mesh tools
export BLENDER_HOME="$HOME/tools/blender-4.3.2-linux-x64"
export PATH="$BLENDER_HOME:$PATH"
EOF

source "$HOME/.bashrc"
blender --version
```

Expected version check:

```text
Blender 4.3.2
```

If you do not want to edit `PATH`, pass the executable path explicitly.

For example, in this repo, mostly you can:

```bash
python scripts/src/visual_mesh_batch_process.py <input> \
  --blender "$HOME/tools/blender-4.3.2-linux-x64/blender"
```

For direct Blender scripts:

```bash
"$HOME/tools/blender-4.3.2-linux-x64/blender" --background \
  --python scripts/src/mesh_repair.py -- input.stl output.stl
```

### 2.2 Windows Notes

Download the official zip from:

```text
https://download.blender.org/release/Blender4.3/blender-4.3.2-windows-x64.zip
```

Extract it, for example to:

```text
C:\tools\blender-4.3.2-windows-x64
```

Add that folder to the user or system `Path` environment variable, open a new
terminal, and verify:

```powershell
blender --version
```

## 3. Python Virtual Environment

The repository does not currently keep a single `requirements.txt`, so install
the Python dependencies used by the mesh scripts into a local venv:

```bash
cd ~/ros2_ws/src/openarm_description
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  numpy \
  scipy \
  networkx \
  trimesh \
  manifold3d \
  coacd \
  pyyaml \
  setuptools
```

What these packages are used for:

| Package | Used by |
| --- | --- |
| `numpy` | CoACD, VHACD, and mesh merge math |
| `scipy` | contact grouping / nearest-neighbor checks in merge/fuse tools |
| `networkx` | graph/component operations used by `trimesh.split()` |
| `trimesh` | STL/OBJ loading, export, concatenation, VHACD wrapper, boolean dispatch |
| `manifold3d` | `trimesh.boolean.union(..., engine="manifold")` |
| `coacd` | `collision_mesh_coacd_merged_process.py` |
| `pyyaml` | visual manual-delete YAML parsing |

Optional for the MJCF conversion workflow:

```bash
.venv/bin/python -m pip install mujoco
```

Quick check:

```bash
.venv/bin/python - <<'PY'
import coacd
import manifold3d
import networkx
import numpy
import scipy
import trimesh
import yaml
print("mesh Python deps OK")
PY
```

## 4. Build and Source the Workspace

Build `openarm_description` so `$(find openarm_description)` and launch files
resolve through the installed ROS package:

```bash
cd ~/ros2_ws
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash
```

Regenerate assembled URDF examples:

```bash
cd ~/ros2_ws/src/openarm_description
bash scripts/generate_urdfs.sh
```

## 5. OpenVDB vdb_tool

The OpenVDB collision workflow calls `vdb_tool` from:

```text
scripts/src/collision_mesh_openvdb_process.py
```

The command shape is:

```text
vdb_tool -read input.stl -mesh2ls voxel=... width=... -close radius=... -ls2mesh adapt=... -write output.obj
```

### 5.1 Try the Ubuntu Package First

On Ubuntu 24.04 and newer, the distro package is usually enough:

```bash
sudo apt update
sudo apt install -y libopenvdb-tools
which vdb_tool
vdb_tool -help
```

On Ubuntu 22.04, `libopenvdb-tools` is OpenVDB 8.1 and does not install
`vdb_tool`; it only installs older tools such as `vdb_print` and `vdb_view`.
For Ubuntu 22.04, build OpenVDB 10.0.1 or newer from source, because
`vdb_tool` was introduced in OpenVDB 10.

### 5.2 Build OpenVDB With vdb_tool

Install build dependencies:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  git \
  libboost-iostreams-dev \
  libboost-system-dev \
  libblosc-dev \
  libimath-dev \
  libopenexr-dev \
  libtbb-dev \
  zlib1g-dev
```

Build and install OpenVDB 10.0.1 locally under `$HOME/tools/openvdb-10.0.1`:

```bash
cd "$HOME/tools"
git clone https://github.com/AcademySoftwareFoundation/openvdb.git openvdb-10.0.1-src
cd openvdb-10.0.1-src
git checkout v10.0.1
mkdir -p build
cd build

cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$HOME/tools/openvdb-10.0.1" \
  -DOPENVDB_BUILD_BINARIES=ON \
  -DOPENVDB_BUILD_PYTHON_MODULE=OFF \
  -DOPENVDB_BUILD_UNITTESTS=OFF \
  -DOPENVDB_BUILD_DOCS=OFF

cmake --build . --parallel "$(nproc)"
cmake --install .
```

Add the installed binary directory to `PATH`:

```bash
cat >> "$HOME/.bashrc" <<'EOF'

# OpenVDB tools for OpenArm collision remeshing
export OPENVDB_HOME="$HOME/tools/openvdb-10.0.1"
export PATH="$OPENVDB_HOME/bin:$PATH"
EOF

source "$HOME/.bashrc"
which vdb_tool
vdb_tool -help
```

If CMake cannot find a dependency, clear the build directory and re-run CMake
with the dependency root explicitly, for example:

```bash
cmake .. \
  -DCMAKE_INSTALL_PREFIX="$HOME/tools/openvdb-10.0.1" \
  -DOPENVDB_BUILD_BINARIES=ON \
  -DTBB_ROOT=/path/to/tbb # libtbb-dev
```

## 6. Verification Checklist

Run these checks from a new terminal:

```bash
cd ~/ros2_ws/src/openarm_description

blender --version
.venv/bin/python -c "import coacd, manifold3d, scipy, trimesh, yaml; print('python deps OK')"
python3 -c "import xml.etree.ElementTree as ET; print('stdlib XML OK')"
which vdb_tool || true
```

Build and URDF generation:

```bash
cd ~/ros2_ws
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --packages-select openarm_description
source install/setup.bash

cd ~/ros2_ws/src/openarm_description
bash scripts/generate_urdfs.sh
```

Mesh tool smoke checks:

```bash
blender --background --python scripts/src/mesh_repair.py -- --help
.venv/bin/python scripts/src/mesh_merge.py --help
```

OpenVDB check, only if using the OpenVDB collision workflow:

```bash
vdb_tool -help
```

## 7. References

- Blender release archive:
  <https://download.blender.org/release/Blender4.3/>
- Blender Linux install notes:
  <https://docs.blender.org/manual/en/latest/getting_started/installing/<user_name>nux.html>
- OpenVDB build documentation:
  <https://www.openvdb.org/documentation/doxygen/build.html>
- OpenVDB dependency documentation:
  <https://www.openvdb.org/documentation/doxygen/dependencies.html>
- OpenVDB GitHub releases:
  <https://github.com/AcademySoftwareFoundation/openvdb/releases>
- Ubuntu `libopenvdb-tools` package search:
  <https://packages.ubuntu.com/<user_name>bopenvdb-tools>
- Ubuntu 22.04 `libopenvdb-tools` contents:
  <https://launchpad.net/ubuntu/jammy/+package/<user_name>bopenvdb-tools>
- Ubuntu 24.04 `libopenvdb-tools` contents:
  <https://launchpad.net/ubuntu/noble/+package/<user_name>bopenvdb-tools>
