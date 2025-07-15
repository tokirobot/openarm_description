# Robot Description files for OpenArm

This package contains description files to generate OpenArm URDFs (Universal Robot Description Files).

To generate or view the URDF, install ROS2, source the setup script, and clone this package into a workspace.

For example, for ROS2 Humble:
```sh
source /opt/ros/humble/setup.bash
mkdir -p ~/ros2_ws/src
git clone https://github.com/enactic/openarm_description.git ~/ros2_ws/src/openarm_description
colcon build
source ~/ros2_ws/install/setup.bash
```

Then to view the bimanual URDF:
```sh
ros2 launch openarm_description display_openarm.launch.py arm_type:=v10 bimanual:=true
```

Or to generate a URDF:
```sh
URDF_NAME=openarm_bimanual.urdf
cd ~/ros2_ws/src/openarm_description/urdf/robot
xacro v10.urdf.xacro arm_type:=v10 bimanual:=true > $URDF_NAME
```
