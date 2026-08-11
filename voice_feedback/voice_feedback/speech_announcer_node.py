#!/usr/bin/env python3
import queue
import threading
import time
import pyttsx3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SpeechAnnouncerNode(Node):
    def __init__(self):
        super().__init__('speech_announcer_node')

        # Filter out transient adjustments (require 0.35s steady state)
        self.declare_parameter('hold_time_sec', 0.35)
        self.hold_time = self.get_parameter('hold_time_sec').value

        self.subscription = self.create_subscription(
            String,
            '/robot_movement_state',
            self.state_callback,
            10
        )

        self.current_candidate_state = None
        self.candidate_first_seen_time = 0.0

        self.last_announced_state = None
        self.speech_queue = queue.Queue()

        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

        self.get_logger().info(
            f"Speech Announcer Node initialized (Hold time: {self.hold_time}s)."
        )

    def state_callback(self, msg: String):
        raw_state = msg.data
        now = time.time()

        # Goal and arrival alerts bypass debounce and speak immediately
        if "goal" in raw_state or "arrived" in raw_state:
            self._enqueue_speech(raw_state)
            return

        if raw_state != self.current_candidate_state:
            self.current_candidate_state = raw_state
            self.candidate_first_seen_time = now
            return

        time_held = now - self.candidate_first_seen_time

        if time_held >= self.hold_time and raw_state != self.last_announced_state:
            self._enqueue_speech(raw_state)

    def _enqueue_speech(self, text: str):
        self.get_logger().info(f"Announcing: '{text}'")
        with self.speech_queue.mutex:
            self.speech_queue.queue.clear()

        self.speech_queue.put(text)
        self.last_announced_state = text

    def _tts_worker(self):
        engine = pyttsx3.init()
        engine.setProperty('rate', 165)

        while rclpy.ok():
            try:
                text = self.speech_queue.get(timeout=1.0)
                engine.say(text)
                engine.runAndWait()
                self.speech_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"TTS error: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = SpeechAnnouncerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()