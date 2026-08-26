#!/usr/bin/env python3
"""Verify that a Foxglove WebSocket advertises and delivers selected topics."""

import argparse
import base64
from collections import Counter
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
from urllib.parse import urlparse


# Foxglove moved its server implementation into the SDK and renamed the v1
# subprotocol. Offering both keeps the check useful with pre-SDK bridges too.
FOXGLOVE_SUBPROTOCOLS = ("foxglove.sdk.v1", "foxglove.websocket.v1")
MESSAGE_DATA_OPCODE = 1


def _read_exact(connection, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("WebSocket closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _client_frame(opcode, payload):
    """Build a masked frame, as required for every client-to-server message."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    header.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header)


def _receive_frame(connection):
    first, second = _read_exact(connection, 2)
    final = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    mask = _read_exact(connection, 4) if masked else None
    payload = _read_exact(connection, length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return final, opcode, payload


def _receive_message(connection):
    opcode = None
    chunks = []
    while True:
        final, frame_opcode, payload = _receive_frame(connection)
        if frame_opcode == 0x8:
            raise ConnectionError("WebSocket server closed the connection")
        if frame_opcode == 0x9:
            connection.sendall(_client_frame(0xA, payload))
            continue
        if frame_opcode == 0xA:
            continue
        if frame_opcode != 0:
            opcode = frame_opcode
        chunks.append(payload)
        if final:
            return opcode, b"".join(chunks)


def _open_websocket(url, timeout):
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
        raise ValueError("URL must be ws://host[:port][/path] or wss://...")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    connection = socket.create_connection((parsed.hostname, port), timeout)
    if parsed.scheme == "wss":
        connection = ssl.create_default_context().wrap_socket(
            connection, server_hostname=parsed.hostname
        )

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    host = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{port}"
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {', '.join(FOXGLOVE_SUBPROTOCOLS)}\r\n\r\n"
    )
    connection.sendall(request.encode("ascii"))

    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(_read_exact(connection, 1))
        if len(response) > 16 * 1024:
            raise ConnectionError("WebSocket response headers are too large")
    header_text = response.decode("iso-8859-1")
    status_line, *header_lines = header_text.split("\r\n")
    if " 101 " not in f" {status_line} ":
        raise ConnectionError(f"WebSocket upgrade failed: {status_line}")
    headers = {
        name.strip().lower(): value.strip()
        for line in header_lines
        if ":" in line
        for name, value in [line.split(":", 1)]
    }
    expected_accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode("ascii")
    if headers.get("sec-websocket-accept") != expected_accept:
        raise ConnectionError("WebSocket server returned an invalid accept key")
    selected_protocol = headers.get("sec-websocket-protocol")
    if selected_protocol not in FOXGLOVE_SUBPROTOCOLS:
        raise ConnectionError("Server did not select the Foxglove WebSocket protocol")
    return connection, selected_protocol


def check_topics(url, requested_topics, duration, timeout):
    connection, selected_protocol = _open_websocket(url, timeout)
    print(f"connected using {selected_protocol}")
    connection.settimeout(timeout)
    advertised = {}
    server_capabilities = None
    advertisement_deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < advertisement_deadline and not all(
            topic in advertised for topic in requested_topics
        ):
            opcode, payload = _receive_message(connection)
            if opcode != 0x1:
                continue
            message = json.loads(payload.decode("utf-8"))
            if message.get("op") == "serverInfo":
                server_capabilities = set(message.get("capabilities", []))
            elif message.get("op") == "advertise":
                advertised.update(
                    (channel["topic"], channel) for channel in message.get("channels", [])
                )

        mutating_capabilities = {
            "clientPublish",
            "services",
            "parameters",
            "parametersSubscribe",
            "connectionGraph",
            "assets",
        }
        if server_capabilities is None:
            raise RuntimeError("Server did not send a serverInfo message")
        unsafe_capabilities = server_capabilities & mutating_capabilities
        if unsafe_capabilities:
            raise RuntimeError(
                "Gateway advertises disabled capabilities: "
                + ", ".join(sorted(unsafe_capabilities))
            )
        print("server capabilities are read-only")

        missing = [topic for topic in requested_topics if topic not in advertised]
        if missing:
            raise RuntimeError(f"Topics not advertised: {', '.join(missing)}")

        subscription_topics = {}
        subscriptions = []
        for subscription_id, topic in enumerate(requested_topics, start=1):
            channel = advertised[topic]
            subscription_topics[subscription_id] = topic
            subscriptions.append(
                {"id": subscription_id, "channelId": channel["id"]}
            )
            print(
                f"advertised {topic}: {channel.get('schemaName', 'unknown schema')} "
                f"({channel.get('encoding', 'unknown encoding')})"
            )
        connection.sendall(
            _client_frame(
                0x1, json.dumps({"op": "subscribe", "subscriptions": subscriptions})
            )
        )

        counts = Counter()
        bytes_received = Counter()
        end = time.monotonic() + duration
        connection.settimeout(min(timeout, max(duration, 0.1)))
        while time.monotonic() < end:
            try:
                opcode, payload = _receive_message(connection)
            except socket.timeout:
                break
            if opcode != 0x2 or len(payload) < 13 or payload[0] != MESSAGE_DATA_OPCODE:
                continue
            subscription_id = struct.unpack("<I", payload[1:5])[0]
            topic = subscription_topics.get(subscription_id)
            if topic:
                counts[topic] += 1
                bytes_received[topic] += len(payload) - 13

        for topic in requested_topics:
            rate = counts[topic] / duration
            print(
                f"received {topic}: {counts[topic]} messages, "
                f"{bytes_received[topic]} payload bytes, {rate:.1f} Hz"
            )
        silent = [topic for topic in requested_topics if counts[topic] == 0]
        if silent:
            raise RuntimeError(f"No payload received for: {', '.join(silent)}")
    finally:
        try:
            connection.sendall(_client_frame(0x8, b""))
        except OSError:
            pass
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Check Foxglove topic advertisements and live payloads"
    )
    parser.add_argument("url", help="Foxglove WebSocket URL")
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        help="required topic; repeat for multiple topics",
    )
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    topics = args.topics or ["/utlidar/cloud", "/utlidar/robot_pose"]
    if args.duration <= 0 or args.timeout <= 0:
        parser.error("duration and timeout must be positive")
    try:
        check_topics(args.url, topics, args.duration, args.timeout)
    except (ConnectionError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
