import importlib.util
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FoxgloveGatewayConfigurationTest(unittest.TestCase):
    def setUp(self):
        with (REPOSITORY_ROOT / "docker/foxglove-gateway.yaml").open() as stream:
            document = yaml.safe_load(stream)
        self.parameters = document["foxglove_bridge"]["ros__parameters"]

    def test_gateway_has_no_remote_mutation_capabilities(self):
        self.assertEqual("127.0.0.1", self.parameters["address"])
        known_capabilities = {
            "clientPublish",
            "services",
            "parameters",
            "parametersSubscribe",
            "connectionGraph",
            "assets",
        }
        self.assertTrue(known_capabilities.isdisjoint(self.parameters["capabilities"]))
        for parameter in (
            "client_topic_whitelist",
            "service_whitelist",
            "param_whitelist",
        ):
            patterns = self.parameters[parameter]
            self.assertFalse(any(re.search(pattern, "/cmd_vel") for pattern in patterns))

    def test_gateway_advertises_required_robot_telemetry(self):
        patterns = self.parameters["topic_whitelist"]
        for topic in ("/utlidar/cloud", "/utlidar/robot_pose", "/tf"):
            self.assertTrue(any(re.search(pattern, topic) for pattern in patterns), topic)
        self.assertFalse(any(re.search(pattern, "/4g_traffic_report") for pattern in patterns))
        self.assertFalse(any(re.search(pattern, "/lowstate") for pattern in patterns))

    def test_robot_dds_uses_ethernet_without_a_host_buffer_requirement(self):
        root = ElementTree.parse(REPOSITORY_ROOT / "docker/cyclonedds-robot.xml")
        namespace = {"c": "https://cdds.io/config"}
        interface = root.find(".//c:NetworkInterface", namespace)
        self.assertIsNotNone(interface)
        self.assertEqual("eth0", interface.attrib["name"])
        self.assertIsNone(root.find(".//c:SocketReceiveBufferSize", namespace))
        output_file = root.find(".//c:Tracing/c:OutputFile", namespace)
        self.assertIsNotNone(output_file)
        self.assertEqual("stderr", output_file.text)


class WebSocketFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_path = REPOSITORY_ROOT / "scripts/check_foxglove_websocket.py"
        spec = importlib.util.spec_from_file_location("foxglove_check", script_path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_client_frames_are_masked_and_recover_the_payload(self):
        payload = b"foxglove"
        frame = self.module._client_frame(0x1, payload)
        self.assertEqual(0x81, frame[0])
        self.assertTrue(frame[1] & 0x80)
        length = frame[1] & 0x7F
        self.assertEqual(len(payload), length)
        mask = frame[2:6]
        recovered = bytes(
            byte ^ mask[index % 4] for index, byte in enumerate(frame[6:])
        )
        self.assertEqual(payload, recovered)


if __name__ == "__main__":
    unittest.main()
