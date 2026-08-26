# British Science Festival Navigation Handoff

This document records the current Dog 2 presentation state and the preferred
path from read-only telemetry to supervised visitor navigation. The public
demonstration should remain non-actuating until the navigation and control
acceptance checks below are complete.

## Current deployment

The Jetson runs `go2-sdk-foxglove_gateway-1` from the
`docker-unitree_ros:latest` image. The service:

- reads native Go2 telemetry through CycloneDDS on the robot-side `eth0`;
- serves Foxglove on port 8765 at the Jetson's Tailscale address;
- advertises an explicit set of standard-message telemetry topics;
- disables client publishing, services, parameters, assets, and connection
  graph capabilities; and
- runs independently of the existing Mid-360 and Fast-LIO containers.

Find the current address and check the service on the Jetson:

```shell
tailscale ip -4
docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' \
  go2-sdk-foxglove_gateway-1
ss -ltnp sport = :8765
```

The bind address supplied when Compose creates the container must be the
Jetson's own Tailscale address:

```shell
cd ~/go2_ros2_sdk/docker
FOXGLOVE_ADDRESS="$(tailscale ip -4)" \
FOXGLOVE_GATEWAY_IMAGE=docker-unitree_ros:latest \
  docker compose -p go2-sdk --profile foxglove up -d --no-build foxglove_gateway
```

Persist the same value in the ignored `docker/.env` if future Compose commands
will not supply it. Normal Docker and host restarts retain the address already
stored in the container configuration.

The last remote payload check delivered `/utlidar/cloud` at approximately
14.6 Hz and `/utlidar/robot_pose` at approximately 18.8 Hz. Recheck from any
authorized tailnet machine with:

```shell
python3 scripts/check_foxglove_websocket.py ws://JETSON_TAILSCALE_IP:8765
```

The check also fails if the bridge advertises a mutation capability. See
[Pi Touchscreen Navigation](pi-touchscreen-nav.md) for Pi installation,
Foxglove, SSH-tunnel, and offline presentation-LAN instructions.

## Repository roles

The companion monorepo should provide the final navigation and actuation stack:

- `go2/lidar` remains the source of the Mid-360 driver, Fast-LIO registered
  cloud, and odometry.
- `go2/control` is the correct home for the reviewed Unitree velocity adapter.
  Its official message packages, state monitor, safety arbiter, and dry-run
  `StopMove` boundary are a better base than the SDK's current Twist handler.
- This SDK provides the isolated Foxglove telemetry edge and any Go2
  compatibility work that is still required.
- `go2-guide-dog-tutorial` remains experimental and should not be connected to
  the real command boundary without its stale-input and watchdog behavior being
  redesigned and tested.

Keep visualization and actuation in separate processes. A display restart must
not restart localization or acquire control of the robot.

## Waypoint navigation reference

[`yehna-kim/unitree-go2-waypoint-nav`](https://github.com/yehna-kim/unitree-go2-waypoint-nav)
was reviewed at commit `007b38e`. It is relevant and contains several ideas
worth adapting:

- a Mid-360, Fast-LIO, RTABMap, and Nav2 Humble pipeline for Jetson ARM64;
- separation of the ROS 2 and Unitree DDS contexts through a subprocess;
- a small `FollowWaypoints` action client that queues `PoseStamped` inputs and
  publishes numbered visualization markers; and
- a velocity clamp and half-second command watchdog.

It should not be deployed unchanged for a public demonstration:

- `unitree_bridge.py` calls `RecoveryStand` and changes speed level during
  startup, so merely starting mapping or localization actuates the robot.
- `robot_driver.py` accepts unauthenticated action datagrams on
  `0.0.0.0:9878`. Any reachable host can request actions or stop.
- `/clear_waypoints` clears local state but does not retain and cancel the active
  Nav2 goal handle, despite the README saying it stops the mission.
- The Foxglove bridge uses its unrestricted defaults while `/goal_pose` is an
  actuator input.
- Shutdown does not issue a final stop, bridge failure is not supervised after
  startup, and command enablement is not tied to an operator lease or safety
  arbiter.
- Several third-party repositories are cloned without commit pins, and the
  project has no automated tests.

The repository is MIT-licensed, so selected code can be adapted with the
required copyright and license notice. Prefer extracting the waypoint-state
logic and RTABMap configuration over replacing the existing monorepo LiDAR and
control stacks or adopting its all-in-one container.

## Recommended implementation sequence

1. Confirm live `/cloud_registered` and `/Odometry` from `go2/lidar`, then
   validate every edge of `map -> odom -> base_link` and the point-cloud frames.
2. Trial the reference repository's RTABMap approach without loading its robot
   driver. Record a venue map and test relocalization after process and Jetson
   restarts.
3. Add a presentation waypoint node to the monorepo. Retain the Nav2 goal handle
   and implement real cancel, clear, feedback, result, and process-shutdown
   behavior with unit tests.
4. Add a disabled-by-default Unitree velocity adapter to `go2/control`. Clamp
   all axes, use a monotonic watchdog, forward zero commands, stop on stale or
   lost input, issue stop on shutdown, and yield to the existing safety arbiter
   and physical operator stop.
5. Expose only named, pre-validated venue waypoints to the touchscreen. The
   Jetson-side service owns the Nav2 action; the Pi never publishes raw velocity
   or Unitree requests.
6. Add a visitor kiosk with large destination buttons, progress, and cancel.
   Keep arbitrary map goals and diagnostics behind an operator mode.
7. Rehearse loss of Pi Wi-Fi, Tailscale, localization, LiDAR, Nav2 output, and
   each container. Test blocked goals and operator stop inside a barrier before
   enabling public interaction.

## Gateway verification

Run from the SDK repository root:

```shell
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/check_foxglove_websocket.py
FOXGLOVE_ADDRESS=127.0.0.1 \
  docker compose -f docker/docker-compose.yml -p go2-sdk \
  --profile foxglove config --quiet
git diff --check
```

The full Python test suite requires `pytest`, which is not part of the current
local development environment. The gateway regression tests use the standard
library test runner plus PyYAML supplied by the ROS environment.
