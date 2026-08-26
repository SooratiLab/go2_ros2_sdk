# Pi Touchscreen Navigation

The presentation system should be built in two stages. First, expose robot
telemetry to the Raspberry Pi through a read-only Foxglove WebSocket. Add
navigation commands only after localization, Nav2, and the robot command
boundary have passed supervised physical tests.

The intended data path is:

```text
Go2 and LiDAR -- ROS 2/DDS --> Jetson -- Foxglove WebSocket --> Tailscale --> Pi
                                      <-- restricted goal API  <--
```

DDS remains on the Jetson's wired `eth0` robot network. Tailscale carries one
TCP WebSocket connection, which is easier to secure and is not dependent on DDS
multicast working across an overlay network.

## Current capability and limits

The read-only gateway advertises standard ROS messages from these sources:

- The Go2's internal LiDAR: `/utlidar/cloud`, `/utlidar/robot_pose`,
  `/utlidar/imu`, and `/utlidar/range_info`.
- Transform and model topics: `/tf`, `/tf_static`, `/robot_description`, and
  `/joint_states`.
- Navigation topics when another stack publishes them: `/cloud_registered`,
  `/Odometry`, `/map`, `/scan`, and `/path`.

Unitree-specific message types are not exposed. The bridge image on the Jetson
does not contain all of their schemas, and one firmware topic has a name that
the ROS graph parser rejects. An allowlist prevents either issue from taking
down the presentation connection.

The gateway has no client-publish, service, parameter, asset, or connection
graph capabilities. It cannot move the robot. This is an intentional boundary,
not a missing setup step.

The SDK's CycloneDDS driver currently discovers the native robot graph but does
not translate the native LiDAR callbacks into its `/robot0/*` topics. The
gateway therefore reads the robot's standard `/utlidar/*` topics directly.
The onboard robot address is a DDS endpoint, not the WebRTC HTTP endpoint
expected by the SDK, so WebRTC is not part of this deployment.

## Start the Jetson gateway

The Foxglove bridge is part of the full-stack image. Build it once on a machine
with package access. Set `FOXGLOVE_ADDRESS` to the Jetson's Tailscale IPv4
address when every device admitted to the lab tailnet is an accepted telemetry
viewer, or when a Tailscale ACL limits the port:

```shell
cd ~/go2_ros2_sdk/docker
cp -n .env.example .env
FOXGLOVE_ADDRESS=100.x.y.z \
  docker compose -p go2-sdk --profile foxglove build foxglove_gateway
FOXGLOVE_ADDRESS=100.x.y.z \
  docker compose -p go2-sdk --profile foxglove up -d foxglove_gateway
```

The explicit project name is important. Other repositories also use a
directory named `docker`, and Compose otherwise groups their containers under
the same default project name.

An offline Jetson can reuse a local image that already contains
`foxglove_bridge`:

```shell
cd ~/go2_ros2_sdk/docker
FOXGLOVE_ADDRESS=100.x.y.z FOXGLOVE_GATEWAY_IMAGE=docker-unitree_ros:latest \
  docker compose -p go2-sdk --profile foxglove up -d --no-build foxglove_gateway
```

Check that it is healthy and listening:

```shell
docker compose -p go2-sdk --profile foxglove ps foxglove_gateway
docker compose -p go2-sdk --profile foxglove logs --tail=100 foxglove_gateway
tailscale ip -4
```

The address is the Jetson's own Tailscale address, not the Pi's. The loopback
default deliberately prevents accidental exposure when the trust boundary has
not been chosen. Even with a Tailscale bind, the service does not listen on the
robot or site LAN. `docker/cyclonedds-robot.xml` expects the robot network to be
`eth0`. Change the interface name there if the Jetson uses a different wired
interface. Do not change it to `tailscale0`; the Foxglove server listens on
Tailscale without sending DDS over Tailscale.

## Verify from the Pi

Install Tailscale on the Pi, join the same tailnet, and confirm the Jetson is
reachable. Replace the address below with the Jetson's Tailscale IPv4 address:

```shell
ping -c 2 100.x.y.z
python3 scripts/check_foxglove_websocket.py ws://100.x.y.z:8765
```

The check succeeds only when both `/utlidar/cloud` and
`/utlidar/robot_pose` are advertised and deliver payloads. A successful TCP
connection alone is not enough. Test a different set explicitly when the
external LiDAR stack is running:

```shell
python3 scripts/check_foxglove_websocket.py ws://100.x.y.z:8765 \
  --topic /cloud_registered --topic /Odometry
```

In Foxglove, choose **Open connection**, select **Foxglove WebSocket**, and use
`ws://100.x.y.z:8765`. A browser-based custom touchscreen interface
is preferable to a full desktop visualization workspace for the final kiosk,
but this connection is useful for validating panels and live data now.

Foxglove publishes an ARM64 Debian package for Ubuntu-based Pi systems at
[foxglove.dev/download](https://foxglove.dev/download). The desktop application
avoids the browser rule that blocks an HTTPS page from opening a non-local
`ws://` connection. Current Foxglove plans also require a developer seat for a
direct WebSocket connection, so confirm the lab account has one before relying
on Foxglove for the public kiosk. The independent check script has no Foxglove
account requirement.

If the whole tailnet is not an appropriate trust boundary, leave the gateway on
`127.0.0.1` and forward it through an authenticated connection instead:

```shell
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8765:127.0.0.1:8765 unitree@100.x.y.z
```

Foxglove then connects to `ws://127.0.0.1:8765`. For an unattended kiosk,
supervise this tunnel with systemd and use a restricted service account. The
application-level allowlist remains useful if an account or device is
compromised, but it does not replace the chosen network access policy.

## Offline presentation fallback

Do not make the live demonstration depend entirely on venue internet or a
Tailscale relay. A small WPA2-protected travel router can provide a private
presentation LAN for the Pi and Jetson while `eth0` remains connected to the
Go2. Bind `FOXGLOVE_ADDRESS` to the Jetson's address on that presentation LAN
and use `ws://JETSON_PRESENTATION_IP:8765` on the Pi. Confirm with `ss -ltnp`
that port 8765 is bound only to the intended presentation address, never
`0.0.0.0` or the robot-side Ethernet address. Rehearse this mode before the
event; changing networks during a live session is not a useful fallback plan.

## How the companion monorepo fits

Several companion packages are more suitable for the final navigation system
than the SDK's all-in-one launch file:

- `go2/lidar` provides the external Mid-360 and Fast-LIO pipeline. Its
  `/cloud_registered` and `/Odometry` outputs are the strongest available basis
  for localization and obstacle data when the external sensor is fitted.
- `go2/control` contains the pinned official Unitree messages, a state monitor,
  safety arbitration, and a dry-run `StopMove` boundary. It is the right home
  for a reviewed velocity adapter, but it does not yet provide one.
- `go2-guide-dog-tutorial` has useful obstacle-avoidance experiments, but its
  command watchdog and stale-detection behavior are not suitable for a public
  real-robot demonstration without further work.

Keep the SDK gateway independent of those processes. This lets the display stay
available if localization is restarted, and avoids coupling visualization to
an actuator process.

## Work required before public navigation

1. **Sensor and transform validation.** Run the external LiDAR/Fast-LIO stack,
   choose the authoritative odometry source, and verify a continuous
   `map -> odom -> base_link` transform tree. Produce a correctly framed scan or
   point cloud for the Nav2 costmaps.
2. **Localization and Nav2 validation.** Create the venue map, exercise relocalization,
   tune footprints and inflation, and reduce the current example speed and
   acceleration limits for a crowded demonstration area.
3. **One safe robot command adapter.** Translate Nav2 velocity output through
   the official Unitree API. It must clamp velocity, forward a real zero command,
   stop on stale input, default to disabled, and yield to the operator stop and
   safety arbiter. Do not connect the SDK's current Twist handler directly.
4. **A restricted goal service.** Accept only named, pre-validated waypoints and
   translate them to the Nav2 `NavigateToPose` action. Expose cancel and status,
   but never expose arbitrary ROS services, raw velocity, or the Unitree request
   topic to the touchscreen.
5. **Touchscreen kiosk.** Present large destination buttons, progress, and a
   cancel button. Keep configuration and free-form goal placement behind an
   operator mode. Foxglove panels can remain available for telemetry and staff
   diagnostics.
6. **Physical acceptance tests.** Test loss of Pi Wi-Fi, loss of Tailscale,
   stale Nav2 output, localization jumps, blocked routes, process restarts, and
   operator stop. Use a barrier and a trained handler for the public session.

For a short science-festival showcase, a small set of waypoints is easier for
visitors to understand and substantially easier to validate than arbitrary map
taps. The operator should retain the physical stop control regardless of what
the touchscreen reports.

Foxglove's direct connections do not translate ROS actions. If a custom
Foxglove extension is retained for visitor controls, let it publish only a
small presentation-specific goal message. A Jetson-side service should validate
that message against the named waypoint set and then own the Nav2 action. Do not
grant the bridge general client-publish capability.
