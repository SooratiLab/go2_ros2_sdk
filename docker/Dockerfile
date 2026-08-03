ARG ROS_BASE_IMAGE=ros:humble-ros-base
FROM ${ROS_BASE_IMAGE}

ARG INSTALL_COCO=false
ARG INSTALL_CPP_LIDAR=false
ARG INSTALL_FULL_STACK=false
ARG APT_FORCE_IPV4=false
ARG UBUNTU_PORTS_MIRROR=http://ports.ubuntu.com/ubuntu-ports

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600

# Install basic requirements
RUN if [ "${APT_FORCE_IPV4}" = "true" ]; then \
      echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4; \
    fi && \
    sed -i "s|http://ports.ubuntu.com/ubuntu-ports|${UBUNTU_PORTS_MIRROR}|g" \
      /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    lsb-release \
    python3-pip \
    portaudio19-dev \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    ros-humble-rmw-cyclonedds-cpp \
    ffmpeg && \
    if [ "${INSTALL_FULL_STACK}" = "true" ]; then \
      apt-get install -y --no-install-recommends ros-humble-rviz2; \
    fi && \
    rm -rf /var/lib/apt/lists/*

# Create workspace
WORKDIR /ros2_ws
ARG PIP_NO_INDEX=false

# Copy dependency metadata separately so normal source edits retain this layer.
COPY requirements-core.txt requirements-coco.txt /tmp/requirements/
COPY wheelhouse /opt/wheelhouse

# Install the normal robot stack. COCO/PyTorch is deliberately opt-in because
# generic ARM64 PyTorch wheels can download gigabytes of CUDA dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_INDEX_ARGS="" && \
    if [ "${PIP_NO_INDEX}" = "true" ]; then PIP_INDEX_ARGS="--no-index"; fi && \
    python3 -m pip install --retries 20 ${PIP_INDEX_ARGS} \
      --find-links=/opt/wheelhouse \
      -r /tmp/requirements/requirements-core.txt && \
    if [ "${INSTALL_COCO}" = "true" ]; then \
      python3 -m pip install --retries 20 ${PIP_INDEX_ARGS} \
        --find-links=/opt/wheelhouse \
        -r /tmp/requirements/requirements-coco.txt; \
    fi

# Resolve ROS dependencies from manifests first so source edits keep this layer.
COPY go2_interfaces/package.xml /tmp/rosdep_ws/go2_interfaces/package.xml
COPY go2_robot_sdk/package.xml /tmp/rosdep_ws/go2_robot_sdk/package.xml
COPY lidar_processor/package.xml /tmp/rosdep_ws/lidar_processor/package.xml
COPY lidar_processor_cpp/package.xml /tmp/rosdep_ws/lidar_processor_cpp/package.xml
COPY speech_processor/package.xml /tmp/rosdep_ws/speech_processor/package.xml
COPY coco_detector/package.xml /tmp/rosdep_ws/coco_detector/package.xml
RUN apt-get update && \
    . /opt/ros/${ROS_DISTRO}/setup.sh && \
    SKIP_KEYS="ament_python" && \
    if [ "${INSTALL_CPP_LIDAR}" != "true" ]; then \
      SKIP_KEYS="${SKIP_KEYS} pcl_ros pcl_conversions"; \
    fi && \
    if [ "${INSTALL_FULL_STACK}" != "true" ]; then \
      SKIP_KEYS="${SKIP_KEYS} twist_mux joy teleop_twist_joy navigation2 nav2_amcl nav2_bringup nav2_map_server nav2_util slam_toolbox foxglove_bridge"; \
    fi && \
    rosdep install --from-paths /tmp/rosdep_ws --ignore-src -r -y \
      --skip-keys "${SKIP_KEYS}" && \
    rm -rf /var/lib/apt/lists/*

# Add the ROS workspace only after third-party dependencies are cached.
COPY . /ros2_ws/src
RUN test -f /ros2_ws/src/go2_robot_sdk/external_lib/aioice/src/aioice/__init__.py || \
    (echo "Missing aioice submodule; clone with --recurse-submodules or run git submodule update --init --recursive" >&2; exit 1)

# Build the workspace
RUN . /opt/ros/${ROS_DISTRO}/setup.sh && \
    if [ "${INSTALL_CPP_LIDAR}" = "true" ]; then \
      colcon build; \
    else \
      colcon build --packages-skip lidar_processor_cpp; \
    fi

# Source ROS2 and workspace in bashrc
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc && \
    echo "source /ros2_ws/install/setup.bash" >> /root/.bashrc

# Set environment variables
ENV ROBOT_IP=""
ENV CONN_TYPE="webrtc"
ENV WEBRTC_SERVER_HOST="0.0.0.0"
ENV WEBRTC_SERVER_PORT="9991"
ENV RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"

# add /ros2_ws to the entrypoint
RUN sed --in-place --expression \
      '$isource "/ros2_ws/install/setup.bash"' \
      /ros_entrypoint.sh

CMD ["ros2", "launch", "go2_robot_sdk", "robot.launch.py", "rviz2:=false", "nav2:=false", "slam:=false", "foxglove:=false", "joystick:=false", "teleop:=false"]
