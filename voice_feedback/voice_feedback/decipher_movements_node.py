#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from action_msgs.msg import GoalStatusArray, GoalStatus


class DecipherNode(Node):
    def __init__(self):
        super().__init__('decipher_node')

        # Thresholds to distinguish normal movement vs obstacle avoidance sharp turns
        self.declare_parameter('lin_threshold', 0.15) # m/s
        self.declare_parameter('ang_threshold', 0.20) # rad/s
        self.declare_parameter('sharp_turn_threshold', 0.55) # rad/s

        self.lin_thresh = self.get_parameter('lin_threshold').value
        self.ang_thresh = self.get_parameter('ang_threshold').value
        self.sharp_thresh = self.get_parameter('sharp_turn_threshold').value

        self.cmd_sub = self.create_subscription(
            Twist,
            'cmd_vel_out',
            self.cmd_callback,
            10
        )

        # RViz / Nav2 goal status monitoring
        self.status_sub = self.create_subscription(
            GoalStatusArray,
            '/navigate_to_pose/_action/status',
            self.status_callback,
            10
        )

        self.state_pub = self.create_publisher(
            String,
            '/robot_movement_state',
            10
        )

        self.last_state = ""
        self.last_goal_status = None
        self.get_logger().info("Guide Dog CmdVel Decipher Node initialized.")


    def status_callback(self, msg: GoalStatusArray):
        if not msg.status_list:
            return

        latest_status = msg.status_list[-1].status

        # Status 2 = EXECUTING (Goal accepted from RViz)
        if latest_status == GoalStatus.STATUS_EXECUTING and self.last_goal_status != GoalStatus.STATUS_EXECUTING:
            self.publish_state("new goal received, starting navigation")

        # Status 4 = SUCCEEDED (Arrived at destination)
        elif latest_status == GoalStatus.STATUS_SUCCEEDED and self.last_goal_status == GoalStatus.STATUS_EXECUTING:
            self.publish_state("arrived at destination")

        self.last_goal_status = latest_status
    
    def cmd_callback(self, msg: Twist):
        vx = msg.linear.x
        vy = msg.linear.y
        wz = msg.angular.z

        state = self.determine_movement(vx, vy, wz)

        if state:
            self.publish_state(state)

    def determine_movement(self, vx: float, vy: float, wz: float) -> str:
        moving_linear = abs(vx) > self.lin_thresh or abs(vy) > self.lin_thresh
        moving_angular = abs(wz) > self.ang_thresh

        if not moving_linear and not moving_angular:
            return "stopped"

        # Sharp turn correction (Nav2 active obstacle avoidance)
        if abs(wz) > self.sharp_thresh and abs(vx) < self.lin_thresh:
            if wz > 0:
                return "avoiding obstacle turning left"
            else:
                return "avoiding obstacle turning right"

        descriptions = []

        if vx > self.lin_thresh:
            descriptions.append("guided path forward")
        elif vx < -self.lin_thresh:
            descriptions.append("backing up")

        if vy > self.lin_thresh:
            descriptions.append("strafing left")
        elif vy < -self.lin_thresh:
            descriptions.append("strafing right")

        if wz > self.ang_thresh:
            descriptions.append("turning left")
        elif wz < -self.ang_thresh:
            descriptions.append("turning right")

        return " and ".join(descriptions)
    
    def publish_state(self, state: str):
        msg_out = String()
        msg_out.data = state
        self.state_pub.publish(msg_out)

        if state != self.last_state:
            self.get_logger().info(f"State: {state}")
            self.last_state = state

def main(args=None):
    rclpy.init(args=args)
    node = DecipherNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()