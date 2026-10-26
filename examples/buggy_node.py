#!/usr/bin/env python3
"""
buggy_robot_controller.py
A realistic ROS 2 node that appears to work initially, but contains
critical robotics loopholes and hazards that AOUL detects.
"""

import math
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from example_interfaces.srv import Trigger
from tf2_ros import Buffer, TransformListener


class BuggyRobotController(Node):

    def __init__(self):
        super().__init__('buggy_robot_controller')

        # LOOPHOLE 1: Default reliable QoS on high-rate sensor topic (LiDAR)
        self.scan_sub = self.create_subscription(
            LaserScan,
            '/scan',
            self.scan_callback,
            10  # Default reliable queue, will fail against best_effort sensor drivers!
        )

        # LOOPHOLE 2: Publishing cmd_vel without any on_shutdown / cleanup hook!
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        # Service client
        self.srv_client = self.create_client(Trigger, '/calibrate_imu')

        # TF2 listener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Control timer (10 Hz)
        self.timer = self.create_timer(0.1, self.control_loop)

        self.latest_scan = None
        self.get_logger().info('Buggy controller initialized.')

    def scan_callback(self, msg):
        # LOOPHOLE 3: Stores scan but no watchdog or freshness check
        self.latest_scan = msg

    def control_loop(self):
        # LOOPHOLE 4: Unprotected TF lookup!
        # If transform is missing or extrapolation occurs, crashes immediately
        trans = self.tf_buffer.lookup_transform('base_link', 'odom', rclpy.time.Time())

        # LOOPHOLE 5: Synchronous service call inside callback -> 100% DEADLOCK!
        if self.srv_client.service_is_ready():
            req = Trigger.Request()
            res = self.srv_client.call(req)  # Deadlock in SingleThreadedExecutor!

        # LOOPHOLE 6: Blocking sleep in callback
        time.sleep(0.02)

        if self.latest_scan:
            # LOOPHOLE 7: Unchecked NaN / Inf in ranges
            # Sensor beam out of range will be 'inf', causing invalid math
            avg_dist = sum(self.latest_scan.ranges) / len(self.latest_scan.ranges)

            cmd = Twist()
            cmd.linear.x = 0.5
            self.cmd_pub.publish(cmd)


def main(args=None):
    rclpy.init(args=args)
    node = BuggyRobotController()
    rclpy.spin(node)
    # LOOPHOLE 8: Node terminated without sending zero velocity Twist to /cmd_vel!
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
