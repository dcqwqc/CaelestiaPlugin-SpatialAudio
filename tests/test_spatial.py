#!/usr/bin/env python3
import importlib.util
import json
import math
import pathlib
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "spatial_controller", ROOT / "scripts/spatial-audio-controller.py"
)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class SpatialTests(unittest.TestCase):
    def run_dsp(self, cfg, frames):
        with tempfile.TemporaryDirectory() as td:
            config = pathlib.Path(td) / "config.json"
            config.write_text(json.dumps(cfg))
            raw = b"".join(struct.pack("<ff", *frame) for frame in frames)
            result = subprocess.run(
                [str(ROOT / "native/spatial-dsp"), str(config)],
                input=raw,
                stdout=subprocess.PIPE,
                check=True,
            )
            return [
                struct.unpack_from("<ff", result.stdout, offset)
                for offset in range(0, len(result.stdout), 8)
            ]

    def test_center_is_transparent(self):
        frames = [(0.8, 0.2), (-0.3, 0.7), (0.0, 0.0)]
        out = self.run_dsp(
            {"pan": 0, "width": 1, "intensity": 1, "movement_ms": 20},
            frames,
        )
        for got, expected in zip(out, frames):
            self.assertAlmostEqual(got[0], expected[0], places=5)
            self.assertAlmostEqual(got[1], expected[1], places=5)

    def test_hard_pan_keeps_both_source_channels(self):
        left = self.run_dsp(
            {"pan": -1, "width": 1, "intensity": 1, "movement_ms": 20},
            [(0.8, 0.2)],
        )[0]
        self.assertAlmostEqual(left[0], 0.5, places=4)
        self.assertAlmostEqual(left[1], 0.0, places=4)

        right = self.run_dsp(
            {"pan": 1, "width": 1, "intensity": 1, "movement_ms": 20},
            [(0.8, 0.2)],
        )[0]
        self.assertAlmostEqual(right[0], 0.0, places=4)
        self.assertAlmostEqual(right[1], 0.5, places=4)

    def test_width_zero_makes_mono(self):
        out = self.run_dsp(
            {"pan": 0, "width": 0, "intensity": 1, "movement_ms": 20},
            [(0.8, 0.2)],
        )[0]
        self.assertAlmostEqual(out[0], 0.5, places=4)
        self.assertAlmostEqual(out[1], 0.5, places=4)

    def test_hrtf_azimuth_mapping(self):
        self.assertEqual(controller.hrtf_azimuth(0), 0)
        self.assertEqual(controller.hrtf_azimuth(-1), 90)
        self.assertEqual(controller.hrtf_azimuth(1), 270)

    def test_hrtf_graph_is_real_sofa_graph(self):
        cfg = {**controller.DEFAULT, "mode": "HRTF"}
        graph = controller.graph(cfg, "physical.sink")
        self.assertIn("type = sofa", graph)
        self.assertIn("label = spatializer", graph)
        self.assertIn('"Radius" = 3.0', graph)
        self.assertIn(str(controller.SOFA), graph)
        self.assertIn('target.object = "physical.sink"', graph)

    def test_pan_matrix_center_is_identity(self):
        self.assertEqual(controller.pan_matrix(0, 1, 1), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(controller.pan_matrix(0.75, 1, 0), (1.0, 0.0, 0.0, 1.0))

    def test_pan_matrix_hard_edges_fold_both_channels_safely(self):
        self.assertEqual(controller.pan_matrix(-1, 1, 1), (0.5, 0.5, 0.0, 0.0))
        self.assertEqual(controller.pan_matrix(1, 1, 1), (0.0, 0.0, 0.5, 0.5))

    def test_pan_graph_has_one_direct_safe_audio_path(self):
        graph = controller.graph(controller.DEFAULT, "physical.sink")
        self.assertIn('target.object = "physical.sink"', graph)
        self.assertIn('node.name = "caelestia_spatial_audio_out"', graph)
        self.assertNotIn("target.object = 0", graph)
        self.assertNotIn("caelestia_spatial_audio_raw", graph)
        self.assertNotIn("Microphone", graph)
        self.assertNotIn("capture_FL", graph)

    def test_pan_graph_is_stereo_virtual_sink(self):
        graph = controller.graph(controller.DEFAULT, "physical.sink")
        self.assertIn("media.class = Audio/Sink", graph)
        self.assertIn("audio.position = [ FL FR ]", graph)
        self.assertIn(controller.VIRTUAL, graph)

    def test_graph_can_use_private_test_sink_name(self):
        graph = controller.graph(
            {**controller.DEFAULT, "mode": "HRTF"},
            "physical.sink",
            "private_test_sink",
        )
        self.assertIn('node.name = "private_test_sink"', graph)
        self.assertIn('node.name = "private_test_sink_hrtf"', graph)
        self.assertNotIn('node.name = "caelestia_spatial_audio"', graph)

    def test_pan_tick_sends_final_value_once(self):
        runtime = controller.Runtime()
        runtime.mode = "Pan"
        runtime.vid = 42
        runtime.start_pan = [0.0, 1.0, 1.0]
        runtime.target_pan = [1.0, 1.0, 1.0]
        runtime.current_pan = [0.99995, 1.0, 1.0]
        runtime.move_duration = 0.02
        runtime.move_started = controller.time.monotonic() - 1.0
        runtime.healthy = lambda check_node=False: True

        sent = []
        runtime._send_pan = lambda *values: sent.append(values) or True

        runtime.tick_pan()
        runtime.tick_pan()

        self.assertEqual(len(sent), 1)
        self.assertEqual(runtime.current_pan, runtime.target_pan)

    def test_hrtf_tick_sends_final_value_once(self):
        runtime = controller.Runtime()
        runtime.mode = "HRTF"
        runtime.vid = 42
        runtime.start_hrtf = [0.0, 0.0, 1.0]
        runtime.target_hrtf = [1.0, 20.0, 0.8]
        runtime.current_hrtf = [0.99995, 19.99995, 0.80001]
        runtime.move_duration = 0.02
        runtime.move_started = controller.time.monotonic() - 1.0
        runtime.healthy = lambda check_node=False: True

        sent = []
        runtime._send_hrtf = lambda *values: sent.append(values) or True

        runtime.tick_hrtf()
        runtime.tick_hrtf()

        self.assertEqual(len(sent), 1)
        self.assertEqual(runtime.current_hrtf, runtime.target_hrtf)

    def test_dry_run_reports_capabilities(self):
        data = json.loads(
            subprocess.check_output(
                [str(ROOT / "scripts/spatial-audio-controller.py"), "dry-run"],
                text=True,
            )
        )
        self.assertIn("physical", data)
        self.assertIn("hrtfAvailable", data)


if __name__ == "__main__":
    unittest.main()
