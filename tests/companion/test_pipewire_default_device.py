# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The default device is metadata, and both PipeWire backends must read it there.

Both backends used to ask a node for `node.default`. No such property exists,
so every device reported `default=False`, selection fell through to "the first
non-monitor entry in graph order", and on a machine with two sources that is
arbitrary. Measured on a Bunny OS guest: capture ran against a silent line-in
while the selected microphone sat beside it in the same graph, and the spoken
interaction ended with "the input device was lost".

The graph fragments below are the shape `pw-dump` really produces, trimmed to
the keys the backends read.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from companion.pipewire import DEFAULT_SINK_KEYS, DEFAULT_SOURCE_KEYS, default_node_name
from companion.speech.capture import PipeWireCaptureBackend
from companion.voice.audio import PipeWireBackend


def _node(name: str, media_class: str, description: str = "") -> dict:
    return {
        "id": abs(hash(name)) % 1000,
        "type": "PipeWire:Interface:Node",
        "info": {
            "state": "suspended",
            "props": {
                "node.name": name,
                "node.description": description or name,
                "media.class": media_class,
            },
        },
    }


def _metadata(**keys: str) -> dict:
    return {
        "id": 30,
        "type": "PipeWire:Interface:Metadata",
        "props": {"metadata.name": "default"},
        "metadata": [
            {"subject": 0, "key": key, "type": "Spa:String:JSON", "value": {"name": value}}
            for key, value in keys.items()
        ],
    }


#: A line-in the daemon created first, and the microphone a person chose.
GRAPH_SOURCES = [
    _node("alsa_input.pci-0000_00_05.0.analog-stereo", "Audio/Source", "Built-in Audio"),
    _node("alsa_output.pci-0000_00_05.0.analog-stereo.monitor", "Audio/Source", "Monitor"),
    _node("bunny-virtual-microphone", "Audio/Source", "BunnyVirtualMicrophone"),
]

GRAPH_SINKS = [
    _node("alsa_output.pci-0000_00_05.0.analog-stereo", "Audio/Sink", "Built-in Audio"),
    _node("bunny-second-sink", "Audio/Sink", "Second"),
]


class MetadataParsingTests(unittest.TestCase):
    def test_the_configured_key_wins_over_the_routed_one(self) -> None:
        graph = [*GRAPH_SOURCES, _metadata(
            **{"default.audio.source": "alsa_input.pci-0000_00_05.0.analog-stereo",
               "default.configured.audio.source": "bunny-virtual-microphone"})]
        self.assertEqual(
            default_node_name(graph, DEFAULT_SOURCE_KEYS), "bunny-virtual-microphone")

    def test_the_routed_key_is_used_when_nothing_was_configured(self) -> None:
        graph = [*GRAPH_SOURCES,
                 _metadata(**{"default.audio.source": "bunny-virtual-microphone"})]
        self.assertEqual(
            default_node_name(graph, DEFAULT_SOURCE_KEYS), "bunny-virtual-microphone")

    def test_a_graph_with_no_default_metadata_expresses_none(self) -> None:
        self.assertEqual(default_node_name(GRAPH_SOURCES, DEFAULT_SOURCE_KEYS), "")

    def test_a_sink_default_is_read_with_the_sink_keys(self) -> None:
        graph = [*GRAPH_SINKS, _metadata(**{"default.audio.sink": "bunny-second-sink"})]
        self.assertEqual(default_node_name(graph, DEFAULT_SINK_KEYS), "bunny-second-sink")
        # ...and the source keys must not pick it up.
        self.assertEqual(default_node_name(graph, DEFAULT_SOURCE_KEYS), "")

    def test_a_value_that_is_not_the_expected_shape_is_ignored(self) -> None:
        graph = [*GRAPH_SOURCES, {
            "props": {"metadata.name": "default"},
            "metadata": [{"key": "default.audio.source", "value": {"unexpected": 1}}],
        }]
        self.assertEqual(default_node_name(graph, DEFAULT_SOURCE_KEYS), "")


class CaptureBackendTests(unittest.TestCase):
    def _discover(self, graph: list) -> list:
        backend = PipeWireCaptureBackend()
        with mock.patch.object(backend, "_inspector_path", "/usr/bin/pw-dump"), \
                mock.patch.object(backend, "_capture_output",
                                  return_value=(0, json.dumps(graph), "")):
            return list(backend.discover())

    def test_the_chosen_microphone_is_the_one_marked_default(self) -> None:
        graph = [*GRAPH_SOURCES,
                 _metadata(**{"default.configured.audio.source": "bunny-virtual-microphone"})]
        devices = self._discover(graph)
        defaults = [device.device_id for device in devices if device.default]
        self.assertEqual(defaults, ["bunny-virtual-microphone"])

    def test_nothing_is_default_when_the_graph_expresses_no_default(self) -> None:
        devices = self._discover(list(GRAPH_SOURCES))
        self.assertEqual([device.device_id for device in devices if device.default], [])

    def test_a_monitor_is_still_recognised_as_a_monitor(self) -> None:
        devices = self._discover(list(GRAPH_SOURCES))
        monitors = [device.device_id for device in devices if device.monitor]
        self.assertEqual(monitors, ["alsa_output.pci-0000_00_05.0.analog-stereo.monitor"])


class PlaybackBackendTests(unittest.TestCase):
    def test_the_chosen_sink_is_the_one_marked_default(self) -> None:
        graph = [*GRAPH_SINKS,
                 _metadata(**{"default.configured.audio.sink": "bunny-second-sink"})]
        backend = PipeWireBackend()
        with mock.patch.object(backend, "_inspector_path", "/usr/bin/pw-dump"), \
                mock.patch.object(backend, "_capture", return_value=(0, json.dumps(graph), "")):
            devices = list(backend.discover())
        self.assertEqual([device.device_id for device in devices if device.default],
                         ["bunny-second-sink"])


if __name__ == "__main__":
    unittest.main()
